"""
llm_chat — 跨 Phase 共享的 LLM 调用（真实 / stub fallback）

Phase 7 / Phase 8 的 Agent 节点统一走此模块：
  - 检测到 LLM_API_KEY 且 openai 可用 → 真实 chat.completions
  - 否则 → 返回 None，由 Agent 自行 fallback 到 stub

.env（democode/.env，与 phase6 llm_coder 相同）：
  LLM_API_KEY
  LLM_BASE_URL   （可选，默认 DashScope 兼容接口）
  LLM_MODEL      （可选；端侧默认 qwen3-32b，非 32B 模型会被自动降级）

端侧小模型策略：本系列 democode 目标为 qwen3-32b（029/phase6）。
若 .env 配置了 qwen3.7-max 等更大模型，默认强制回退到 qwen3-32b。
设 DEMOCODE_EDGE_MODEL=0 可关闭强制（不推荐）。
"""

from __future__ import annotations

import json
import os
import re
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_LLM_MODEL = "qwen3-32b"
DEFAULT_LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 显式允许的端侧模型（小写比较）
ALLOWED_EDGE_MODELS = frozenset({
    "qwen3-32b",
    "qwen3_32b",
    "qwen-32b",
})

_ENV_LOADED = False
_FORCE_STUB = False


def set_force_stub(enabled: bool = True) -> None:
    """演示脚本 --no-llm 时强制 stub，不发起 API 调用。"""
    global _FORCE_STUB
    _FORCE_STUB = enabled


def _load_dotenv_once() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True

    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=False)
    except ImportError:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value


def _edge_model_enforced() -> bool:
    val = os.environ.get("DEMOCODE_EDGE_MODEL", "1").strip().lower()
    return val not in ("0", "false", "no", "off")


def resolve_llm_model(*, warn: bool = True) -> str:
    """
    解析实际使用的模型名。端侧 demo 默认锁定 qwen3-32b。

    - 未设置 LLM_MODEL → qwen3-32b
    - 已设置且为允许列表 / 名称含 32b → 使用该值
    - 已设置为更大模型（如 qwen3.7-max）→ 强制 qwen3-32b 并告警
    """
    _load_dotenv_once()
    configured = os.environ.get("LLM_MODEL", "").strip()
    if not configured:
        return DEFAULT_LLM_MODEL

    normalized = configured.lower().replace("_", "-")
    if "32b" in normalized or normalized in ALLOWED_EDGE_MODELS:
        return configured

    if _edge_model_enforced():
        if warn:
            msg = (
                f"LLM_MODEL={configured!r} 非端侧 32B，"
                f"已改用 {DEFAULT_LLM_MODEL!r}（DEMOCODE_EDGE_MODEL=0 可关闭）"
            )
            warnings.warn(msg, stacklevel=3)
            print(f"  ⚠ {msg}")
        return DEFAULT_LLM_MODEL

    return configured


def resolve_llm_base_url() -> str:
    _load_dotenv_once()
    return os.environ.get("LLM_BASE_URL", DEFAULT_LLM_BASE_URL)


def is_llm_available() -> bool:
    _load_dotenv_once()
    if _FORCE_STUB:
        return False
    if not os.environ.get("LLM_API_KEY"):
        return False
    try:
        import openai  # noqa: F401
        return True
    except ImportError:
        return False


def llm_mode_label() -> str:
    if _FORCE_STUB:
        return "stub (--no-llm)"
    if not is_llm_available():
        key = "无 LLM_API_KEY" if not os.environ.get("LLM_API_KEY") else "openai 未安装"
        return f"stub ({key})"
    model = resolve_llm_model()
    base = resolve_llm_base_url()
    return f"llm ({model} @ {base})"


def _extract_json(text: str) -> Any:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        return json.loads(m.group(1).strip())
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError(f"无法从 LLM 响应解析 JSON: {text[:200]}...")


def chat_complete(
    system: str,
    user: str,
    *,
    json_mode: bool = False,
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> Optional[str]:
    """
    发起一次 chat completion。不可用时返回 None（不抛错）。
    json_mode=True 时请求 JSON 对象响应（兼容 OpenAI response_format）。
    """
    if not is_llm_available():
        return None

    from openai import OpenAI

    _load_dotenv_once()
    base_url = resolve_llm_base_url()
    client = OpenAI(
        api_key=os.environ["LLM_API_KEY"],
        base_url=base_url,
        timeout=120.0,
    )
    model = resolve_llm_model()

    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        # 与 phase6 llm_coder 一致：关闭 thinking，模拟端侧 token 约束
        "extra_body": {"enable_thinking": False},
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("LLM 返回空 content")
    return content.strip()


def chat_json(system: str, user: str, **kwargs: Any) -> Optional[Any]:
    """chat_complete + JSON 解析。失败时 raise，由 Agent 捕获后 fallback stub。"""
    raw = chat_complete(system, user, json_mode=True, **kwargs)
    if raw is None:
        return None
    return _extract_json(raw)


def format_manifest_for_prompt(task_context: Dict[str, Any], max_items: int = 8) -> str:
    """把 inject 解析结果压缩成 prompt 片段。"""
    lines: List[str] = []
    for c in (task_context.get("manifest_constraints") or [])[:max_items]:
        lines.append(
            f"- [{c.get('id')}] rule_id={c.get('rule_id')} "
            f"enforcement={c.get('enforcement')} {c.get('how', c.get('title', ''))[:80]}"
        )
    for p in (task_context.get("manifest_patterns") or [])[:max_items]:
        lines.append(f"- [{p.get('id')}] pattern: {p.get('how', p.get('title', ''))[:80]}")
    preview = task_context.get("memory_context_preview")
    if preview:
        lines.append(f"\n--- InjectManifest context_text ---\n{preview[:1200]}")
    return "\n".join(lines) if lines else "(无 manifest 约束)"
