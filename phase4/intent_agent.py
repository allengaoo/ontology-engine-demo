"""
IntentAgent：意图理解Agent

职责：
  1. 解析用户自然语言意图
  2. 提取关键实体和目标
  3. 写入CONTEXT层

有 LLM_API_KEY 时走真实模型；否则 keyword stub。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional
DEMOCODE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEMOCODE_ROOT))

from llm_chat import chat_json, format_manifest_for_prompt, is_llm_available  # noqa: E402

from .multi_agent_router import Task, AgentResult


_INTENT_SYSTEM = """你是半闭域采购系统的意图解析器。根据任务描述输出 JSON，字段：
- type: kafka_idempotency_fix | threshold_adjustment | unknown
- target_file: 字符串（幂等场景）
- from_value / to_value: 整数（阈值场景）
- needs_compliance_check: bool
- pattern_ids: 字符串数组（若上下文给出则引用）
只输出 JSON。"""


class IntentAgent:
    """意图理解Agent"""

    def __init__(self):
        self.name = "IntentAgent"

    def execute(self, task: Task, router) -> AgentResult:
        print(f"\n[{self.name}] 开始执行任务...")
        intent = self._parse_with_llm(task) or self._parse_stub(task)
        print(f"  解析结果：{intent}")
        if is_llm_available() and intent.get("_source") == "llm":
            print("  [LLM] 意图由大模型解析")

        return AgentResult(
            status="completed",
            output=intent,
            next_agent="OntologyAgent",
        )

    def _parse_with_llm(self, task: Task) -> Optional[dict]:
        ctx = task.context or {}
        user = (
            f"任务描述：{task.description}\n\n"
            f"InjectManifest 摘要：\n{format_manifest_for_prompt(ctx)}\n"
        )
        try:
            data = chat_json(_INTENT_SYSTEM, user, max_tokens=512)
            if not data:
                return None
            data["_source"] = "llm"
            return data
        except Exception as exc:
            print(f"  ⚠ LLM 意图解析失败，fallback stub: {exc}")
            return None

    def _parse_stub(self, task: Task) -> dict:
        desc = task.description
        desc_lower = desc.lower()
        if any(k in desc_lower for k in ("kafka", "idempotency", "幂等", "procurement")):
            intent = self._parse_procurement_fix(desc, task)
        elif "阈值" in desc and ("调整" in desc or "→" in desc or "->" in desc):
            intent = self._parse_threshold_adjustment(desc)
        else:
            intent = {"type": "unknown", "raw": desc}
        intent["_source"] = "stub"
        return intent

    def _parse_threshold_adjustment(self, desc: str) -> dict:
        numbers = re.findall(r"\d+", desc)
        result = {
            "type": "threshold_adjustment",
            "target": "认证有效期",
            "raw": desc,
        }
        if len(numbers) >= 2:
            result["from_value"] = int(numbers[0])
            result["to_value"] = int(numbers[1])
        if "安全" in desc or "确保" in desc:
            result["constraint"] = "needs_safety_verification"
        return result

    def _parse_procurement_fix(self, desc: str, task: Task) -> dict:
        patterns = (task.context or {}).get("manifest_patterns", [])
        pattern_ids = [p.get("id") for p in patterns if p.get("id")]
        return {
            "type": "kafka_idempotency_fix",
            "target_file": "procurement_service.py",
            "raw": desc,
            "pattern_ids": pattern_ids,
            "needs_compliance_check": True,
        }
