"""
Phase 8 scope_loader — 扩展 BSA / CA 的 TOML 映射
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import Dict

PHASE7 = Path(__file__).parent.parent / "phase7"
sys.path.insert(0, str(PHASE7))

from agent_memory_scope import AgentMemoryScope, AgentMemoryScopeRegistry  # noqa: E402
from scope_loader import (  # noqa: E402
    FILENAME_TO_AGENT as _BASE_MAP,
    _load_toml_file,
    _validate_scope_data,
    diff_registries,
)

PHASE8_DEFAULT_SCOPES: Dict[str, AgentMemoryScope] = {
    "BusinessStructureAgent": AgentMemoryScope(
        agent_name="BusinessStructureAgent",
        domains=["code-arch", "purchasing"],
        tiers=["hot", "warm"],
        read_layers=["critical", "rule", "context"],
        write_layers=[],
        budget_multiplier=1.0,
        concept_hints=["architecture", "compliance", "pattern", "idempotency"],
    ),
    "CodingAgent": AgentMemoryScope(
        agent_name="CodingAgent",
        domains=["code-arch"],
        tiers=["hot"],
        read_layers=["critical", "rule", "pattern"],
        write_layers=[],
        budget_multiplier=0.8,
        concept_hints=["idempotency", "procurement", "architecture"],
    ),
}

FILENAME_TO_AGENT: Dict[str, str] = {
    **_BASE_MAP,
    "business_structure_agent": "BusinessStructureAgent",
    "coding_agent": "CodingAgent",
}


def load_scope_from_toml(path: Path) -> AgentMemoryScope:
    stem = path.stem
    agent_name = FILENAME_TO_AGENT.get(stem)
    if agent_name is None:
        raise ValueError(
            f"无法识别文件名 {path.name}，支持：{list(FILENAME_TO_AGENT.keys())}"
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


def load_scopes_from_dir(roles_dir: Path, fallback: bool = True) -> AgentMemoryScopeRegistry:
    if not roles_dir.exists():
        if fallback:
            warnings.warn(f"roles 目录不存在：{roles_dir}，使用 Phase 8 默认 scope")
            return AgentMemoryScopeRegistry(PHASE8_DEFAULT_SCOPES)
        raise FileNotFoundError(f"roles 目录不存在：{roles_dir}")

    scopes = dict(PHASE8_DEFAULT_SCOPES)
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
        msg = "phase8 scope_loader 部分失败：\n" + "\n".join(errors)
        if fallback:
            warnings.warn(msg)
        else:
            raise ValueError(msg)

    print(f"  [scope_loader] Phase 8 已从 roles/ 加载：{loaded}")
    return AgentMemoryScopeRegistry(scopes)


__all__ = ["load_scopes_from_dir", "load_scope_from_toml", "diff_registries", "FILENAME_TO_AGENT"]
