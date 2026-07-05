"""
CoderAgent — 方案落地 + ConstraintMemory 校验（Phase 7 P1）

有 LLM_API_KEY 时由大模型生成代码；否则 stub。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

DEMOCODE_ROOT = Path(__file__).parent.parent
PHASE6 = DEMOCODE_ROOT / "phase6"
sys.path.insert(0, str(PHASE6))
sys.path.insert(0, str(DEMOCODE_ROOT))

from code_validator import CodeValidator  # noqa: E402
from llm_chat import chat_complete, format_manifest_for_prompt, is_llm_available  # noqa: E402

from phase4.multi_agent_router import AgentResult, Task


_CODER_SYSTEM = """你是 Python 业务代码生成器（半闭域采购/Kafka 幂等场景）。
根据方案和 ConstraintMemory 生成完整 Python 源码。
要求：
- 只输出纯 Python 代码，不要 markdown 围栏
- 领域层不得 import infrastructure/adapter/kafka_producer 等适配层（ARCH-001）
- 满足 manifest 中 enforcement=reject 的约束
- 代码应可运行，包含必要 docstring"""


class CoderAgent:
    """代码生成 Agent"""

    def __init__(self):
        self.name = "CoderAgent"

    def execute(self, task: Task, router) -> AgentResult:
        print(f"\n[{self.name}] 开始执行任务...")
        proposal = task.context.get("proposal", {})
        intent = task.context.get("intent", {})
        print(f"  方案：{proposal.get('proposal_id')} action={proposal.get('action')}")

        code = self._generate_with_llm(task, proposal, intent)
        if code is None:
            code = self._generate_code_stub(proposal, intent)
        else:
            print("  [LLM] 代码由大模型生成")

        print(f"  生成代码：{len(code.splitlines())} 行")

        constraints = task.context.get("manifest_constraints", [])
        reject_ids = [
            c["id"] for c in constraints
            if c.get("enforcement") == "reject"
        ]
        if reject_ids:
            print(f"  manifest 约束（reject）：{reject_ids}")

        validator = self._build_validator(task)
        if validator:
            report = validator.validate(code)
            print(f"  CodeValidator: {report.summary()}")
            if not report.passed:
                return AgentResult(
                    status="rejected",
                    output={"code": code, "validation": report.summary()},
                    reason=report.violations[0].detail if report.violations else "校验失败",
                )

        return AgentResult(
            status="completed",
            output={
                "code": code,
                "proposal_id": proposal.get("proposal_id"),
                "validated": validator is not None,
            },
        )

    def _generate_with_llm(
        self,
        task: Task,
        proposal: Dict[str, Any],
        intent: Dict[str, Any],
    ) -> Optional[str]:
        ctx = task.context or {}
        user = (
            f"任务：{task.description}\n"
            f"意图：{intent}\n"
            f"方案：{proposal}\n\n"
            f"ConstraintMemory：\n{format_manifest_for_prompt(ctx)}\n"
        )
        try:
            raw = chat_complete(_CODER_SYSTEM, user, json_mode=False, max_tokens=2048)
            if not raw:
                return None
            return self._strip_code_fence(raw)
        except Exception as exc:
            print(f"  ⚠ LLM 代码生成失败，fallback stub: {exc}")
            return None

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        text = text.strip()
        m = re.search(r"```(?:python)?\s*([\s\S]*?)```", text)
        if m:
            return m.group(1).strip()
        return text

    def _build_validator(self, task: Task) -> Optional[CodeValidator]:
        graph = task.context.get("_code_arch_graph")
        if graph is None:
            return None
        return CodeValidator(graph)

    def _generate_code_stub(self, proposal: Dict[str, Any], intent: Dict[str, Any]) -> str:
        action = proposal.get("action", "")

        if action == "apply_idempotency_pattern":
            return '''\
"""procurement_service — Kafka 幂等消费 stub（Phase 7 demo）"""
from infrastructure.persistence import get_session

PROCESSED = set()

def handle_procurement_event(event_id: str, payload: dict) -> None:
    if event_id in PROCESSED:
        return
    with get_session() as session:
        if session.query_processed(event_id):
            return
        _create_purchase_order(payload, session)
        session.mark_processed(event_id)
    PROCESSED.add(event_id)
'''

        if action in ("update_threshold", "keep_threshold_add_warning"):
            to_val = proposal.get("to_value", 30)
            return f'''\
"""supplier_gate — 认证阈值校验 stub"""
CERT_THRESHOLD_DAYS = {to_val}

def check_supplier_cert(remaining_days: int) -> bool:
    return remaining_days >= CERT_THRESHOLD_DAYS
'''

        return f"# stub for action={action}\npass\n"
