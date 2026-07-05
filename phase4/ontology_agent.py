"""
OntologyAgent：规则分析与方案生成Agent

有 LLM_API_KEY 时由大模型生成 proposal；否则规则 stub。
"""

from __future__ import annotations

import json
import sys
from typing import Optional
from pathlib import Path

DEMOCODE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEMOCODE_ROOT))

from llm_chat import chat_json, format_manifest_for_prompt  # noqa: E402

from .multi_agent_router import Task, AgentResult


_ONTOLOGY_SYSTEM = """你是半闭域采购/架构合规系统的方案规划器（OntologyAgent）。
根据意图与 ConstraintMemory 生成调整方案 JSON，字段示例：
{
  "proposal_id": "v1",
  "action": "apply_idempotency_pattern | update_threshold | keep_threshold_add_warning",
  "target": "描述",
  "from_value": 30,
  "to_value": 15,
  "measures": ["..."],
  "pattern_ids": ["PAT-..."],
  "constraints_honored": ["CN-..."],
  "confidence": 0.0-1.0,
  "reason": "可选说明"
}
必须遵守 manifest 中 enforcement=reject 的约束；若 SimAgent 反馈供应商不合格，应保守修正。
只输出 JSON。"""


class OntologyAgent:
    """规则分析Agent"""

    def __init__(self):
        self.name = "OntologyAgent"
        self.version = 1

    def execute(self, task: Task, router) -> AgentResult:
        print(f"\n[{self.name}] 开始执行任务... (方案 v{self.version})")

        critical_rules = self._get_critical_rules(task)
        print(f"  读取 CRITICAL 层：{len(critical_rules)} 条约束")
        if task.context.get("manifest_constraints"):
            print(f"    （来自 InjectManifest：{[c.get('id') for c in critical_rules[:4]]}）")

        intent = task.context.get("intent", {})
        bg = (task.context or {}).get("_bg_results", [])
        feedback = task.feedback or (bg[-1]["result"] if bg else None)

        proposal = self._generate_with_llm(task, intent, critical_rules, feedback)
        if proposal is None:
            if feedback:
                proposal = self._revise_proposal_stub(intent, feedback)
            else:
                proposal = self._generate_initial_proposal_stub(intent, critical_rules)
        else:
            print("  [LLM] 方案由大模型生成")

        print(f"  生成方案：{proposal}")

        return AgentResult(
            status="needs_verification",
            output=proposal,
            next_agent="SimAgent",
        )

    def _generate_with_llm(
        self,
        task: Task,
        intent: dict,
        critical_rules: list,
        feedback: Optional[str],
    ) -> Optional[dict]:
        ctx = task.context or {}
        parts = [
            f"意图：{json.dumps(intent, ensure_ascii=False)}",
            f"ConstraintMemory：\n{format_manifest_for_prompt(ctx)}",
            f"关键规则：{json.dumps(critical_rules[:6], ensure_ascii=False)}",
        ]
        if feedback:
            parts.append(f"SimAgent/上轮反馈（须修正）：{feedback}")
        user = "\n\n".join(parts)
        try:
            data = chat_json(_ONTOLOGY_SYSTEM, user, max_tokens=1024)
            if not data:
                return None
            data.setdefault("proposal_id", f"v{self.version}")
            data["_source"] = "llm"
            return data
        except Exception as exc:
            print(f"  ⚠ LLM 方案生成失败，fallback stub: {exc}")
            return None

    def _get_critical_rules(self, task: Task) -> list:
        constraints = (task.context or {}).get("manifest_constraints")
        if constraints:
            return [
                {
                    "id": c.get("id"),
                    "desc": c.get("desc") or c.get("title"),
                    "rule_id": c.get("rule_id"),
                    "enforcement": c.get("enforcement"),
                }
                for c in constraints
            ]
        return [
            {"id": "CR-001", "desc": "认证剩余天数 >= 30 天"},
            {"id": "CR-002", "desc": "供应商状态=active 且合同状态=valid"},
            {"id": "CR-003", "desc": "未结金额 <= 信用额度"},
            {"id": "CR-004", "desc": "单笔采购 <= 50万"},
        ]

    def _generate_initial_proposal_stub(self, intent: dict, critical_rules: list) -> dict:
        if intent.get("type") == "kafka_idempotency_fix":
            patterns = intent.get("pattern_ids") or []
            return {
                "proposal_id": f"v{self.version}",
                "action": "apply_idempotency_pattern",
                "target": intent.get("target_file", "procurement_service.py"),
                "measures": ["idempotency_key", "processed_events 去重表"],
                "pattern_ids": patterns,
                "constraints_honored": [c.get("id") for c in critical_rules],
                "confidence": 0.85,
                "_source": "stub",
            }

        from_val = intent.get("from_value", 30)
        to_val = intent.get("to_value", 15)
        return {
            "proposal_id": f"v{self.version}",
            "action": "update_threshold",
            "target": "认证有效期阈值",
            "from_value": from_val,
            "to_value": to_val,
            "additional_measures": ["增加预警机制（45天）"],
            "confidence": 0.8,
            "_source": "stub",
        }

    def _revise_proposal_stub(self, intent: dict, feedback: str) -> dict:
        self.version += 1
        if "不合格" in feedback or "仍" in feedback:
            return {
                "proposal_id": f"v{self.version}",
                "action": "keep_threshold_add_warning",
                "target": "认证有效期阈值",
                "from_value": 30,
                "to_value": 30,
                "additional_measures": ["增加45天预警", "Beta供应商专项监控"],
                "confidence": 0.9,
                "reason": "基于SimAgent反馈修正",
                "_source": "stub",
            }
        return self._generate_initial_proposal_stub(intent, [])
