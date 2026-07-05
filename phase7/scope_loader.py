"""
scope_loader — 从 roles/ TOML 文件加载 AgentMemoryScope（Phase 7 P2）

设计原则：
  - 字段合法性在加载时校验，不等到运行时静默失败
  - 未知字段报警告，不报错（向前兼容）
  - 文件名即 Agent 名的 snake_case 映射
  - 加载失败回退到 DEFAULT_AGENT_SCOPES，不影响运行

用法：
  from scope_loader import load_scopes_from_dir
  registry = load_scopes_from_dir(Path("phase7/roles"))
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import Dict, Optional

# Python 3.11+ 内置 tomllib；旧版本需要 pip install tomli；均不可用时用内置简单解析器
try:
    import tomllib                          # type: ignore[import]
    _TOMLLIB_AVAILABLE = True
except ImportError:
    try:
        import tomli as tomllib             # type: ignore[import]
        _TOMLLIB_AVAILABLE = True
    except ImportError:
        _TOMLLIB_AVAILABLE = False

from agent_memory_scope import AgentMemoryScope, AgentMemoryScopeRegistry, DEFAULT_AGENT_SCOPES

# ── 合法值白名单 ──────────────────────────────────────────────────────────────
VALID_TIERS   = {"hot", "warm", "cold", "archived"}
VALID_LAYERS  = {"critical", "rule", "context", "background", "pattern"}

# TOML 文件名（snake_case）→ Agent 名（PascalCase）
FILENAME_TO_AGENT: Dict[str, str] = {
    "intent_agent":   "IntentAgent",
    "ontology_agent": "OntologyAgent",
    "sim_agent":      "SimAgent",
    "coder_agent":    "CoderAgent",
}


# ── 简单 TOML 解析（当 tomllib/tomli 均不可用时的后备）────────────────────────
def _parse_toml_simple(text: str) -> dict:
    """
    极简 TOML 解析器：只支持 [section] + key = value / key = [list]。
    足够应对 roles/*.toml 的格式。
    """
    result: dict = {}
    section: Optional[str] = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            result.setdefault(section, {})
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip()

        # 列表
        if v.startswith("[") and v.endswith("]"):
            items = v[1:-1].split(",")
            parsed = [i.strip().strip('"').strip("'") for i in items if i.strip()]
        # 字符串
        elif v.startswith('"') or v.startswith("'"):
            parsed = v.strip('"').strip("'")
        # 浮点
        elif "." in v:
            try:
                parsed = float(v)
            except ValueError:
                parsed = v
        # 整数
        else:
            try:
                parsed = int(v)
            except ValueError:
                parsed = v

        target = result[section] if section else result
        target[k] = parsed

    return result


def _load_toml_file(path: Path) -> dict:
    """加载单个 TOML 文件，自动降级到简单解析器。"""
    text = path.read_text(encoding="utf-8")
    if _TOMLLIB_AVAILABLE:
        return tomllib.loads(text)
    return _parse_toml_simple(text)


# ── 校验逻辑 ─────────────────────────────────────────────────────────────────
def _validate_scope_data(agent_name: str, data: dict, path: Path) -> None:
    """校验 TOML 数据，非法值直接 raise，未知字段只告警。"""
    mem = data.get("memory", {})

    tiers = mem.get("tiers", [])
    bad_tiers = [t for t in tiers if t not in VALID_TIERS]
    if bad_tiers:
        raise ValueError(
            f"[{path.name}] {agent_name}.tiers 包含非法值：{bad_tiers}，"
            f"允许：{sorted(VALID_TIERS)}"
        )

    for layer_field in ("read_layers", "write_layers"):
        layers = mem.get(layer_field, [])
        bad = [l for l in layers if l not in VALID_LAYERS]
        if bad:
            raise ValueError(
                f"[{path.name}] {agent_name}.{layer_field} 包含非法值：{bad}，"
                f"允许：{sorted(VALID_LAYERS)}"
            )

    bm = mem.get("budget_multiplier", 1.0)
    if not (0.0 < bm <= 5.0):
        raise ValueError(
            f"[{path.name}] {agent_name}.budget_multiplier={bm} 超出合法范围 (0, 5]"
        )

    # 未知字段只告警
    known_mem_fields = {"domains", "tiers", "read_layers", "write_layers", "budget_multiplier"}
    unknown = set(mem.keys()) - known_mem_fields
    if unknown:
        warnings.warn(
            f"[{path.name}] {agent_name}.memory 包含未知字段（忽略）：{unknown}",
            stacklevel=4,
        )


# ── 公开接口 ─────────────────────────────────────────────────────────────────
def load_scope_from_toml(path: Path) -> AgentMemoryScope:
    """从单个 TOML 文件加载 AgentMemoryScope，校验失败直接 raise。"""
    stem = path.stem  # e.g. "intent_agent"
    agent_name = FILENAME_TO_AGENT.get(stem)
    if agent_name is None:
        raise ValueError(
            f"无法识别文件名 {path.name}，"
            f"支持：{list(FILENAME_TO_AGENT.keys())}"
        )

    data = _load_toml_file(path)
    _validate_scope_data(agent_name, data, path)

    mem = data.get("memory", {})
    hints = data.get("concept_hints", {})

    return AgentMemoryScope(
        agent_name=agent_name,
        domains=mem.get("domains", []),
        tiers=mem.get("tiers", []),
        read_layers=mem.get("read_layers", []),
        write_layers=mem.get("write_layers", []),
        budget_multiplier=float(mem.get("budget_multiplier", 1.0)),
        concept_hints=hints.get("keywords", []),
    )


def load_scopes_from_dir(
    roles_dir: Path,
    fallback: bool = True,
) -> AgentMemoryScopeRegistry:
    """
    从 roles/ 目录加载所有 *.toml 文件，构建 AgentMemoryScopeRegistry。

    Args:
        roles_dir:  包含 *.toml 文件的目录
        fallback:   True 时加载失败回退到 DEFAULT_AGENT_SCOPES（不中断启动）

    Returns:
        AgentMemoryScopeRegistry
    """
    if not roles_dir.exists():
        if fallback:
            warnings.warn(f"roles 目录不存在：{roles_dir}，使用默认 scope", stacklevel=2)
            return AgentMemoryScopeRegistry()
        raise FileNotFoundError(f"roles 目录不存在：{roles_dir}")

    scopes: Dict[str, AgentMemoryScope] = dict(DEFAULT_AGENT_SCOPES)  # 先填默认值
    loaded = []
    errors = []

    for toml_path in sorted(roles_dir.glob("*.toml")):
        try:
            scope = load_scope_from_toml(toml_path)
            scopes[scope.agent_name] = scope
            loaded.append(scope.agent_name)
        except Exception as exc:
            errors.append(f"  ✗ {toml_path.name}: {exc}")

    if errors:
        msg = "scope_loader 加载部分失败（已回退到默认值）：\n" + "\n".join(errors)
        if fallback:
            warnings.warn(msg, stacklevel=2)
        else:
            raise ValueError(msg)

    print(f"  [scope_loader] 已从 roles/ 加载：{loaded}")
    return AgentMemoryScopeRegistry(scopes)


def diff_registries(
    old: AgentMemoryScopeRegistry,
    new: AgentMemoryScopeRegistry,
) -> str:
    """输出两个 registry 的 scope 差异，用于 Plan Mode 的 diff 展示。"""
    lines = ["## scope 变更（TOML 热加载前 → 后）"]
    for agent_name in sorted(set(old.list_agents()) | set(new.list_agents())):
        try:
            old_s = old.for_agent(agent_name).summary()
        except KeyError:
            old_s = "（新增）"
        try:
            new_s = new.for_agent(agent_name).summary()
        except KeyError:
            new_s = "（已移除）"

        if old_s != new_s:
            lines.append(f"[{agent_name}]")
            lines.append(f"  旧: {old_s}")
            lines.append(f"  新: {new_s}")
        else:
            lines.append(f"[{agent_name}] 无变化")
    return "\n".join(lines)
