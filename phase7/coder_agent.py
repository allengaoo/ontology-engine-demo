"""
CoderAgent — 方案落地 + ConstraintMemory 校验（Phase 7 P1）

SimAgent 通过后生成代码 stub，并用 code-arch 域的 ConstraintMemory 做规则校验。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

DEMOCODE_ROOT = Path(__file__).parent.parent
PHASE6 = DEMOCODE_ROOT / "phase6"
sys.path.insert(0, str(PHASE6))

from code_validator import CodeValidator  # noqa: E402

from phase4.multi_agent_router import AgentResult, Task


class CoderAgent:
    """代码生成 Agent（stub + 校验，不调用 LLM）"""

    def __init__(self):
        self.name = "CoderAgent"

    def execute(self, task: Task, router) -> AgentResult:
        print(f"\n[{self.name}] 开始执行任务...")
        proposal = task.context.get("proposal", {})
        intent = task.context.get("intent", {})
        print(f"  方案：{proposal.get('proposal_id')} action={proposal.get('action')}")

        code = self._generate_code(proposal, intent)
        print(f"  生成代码 stub：{len(code.splitlines())} 行")

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

    def _build_validator(self, task: Task) -> Optional[CodeValidator]:
        graph = task.context.get("_code_arch_graph")
        if graph is None:
            return None
        return CodeValidator(graph)

    def _generate_code(self, proposal: Dict[str, Any], intent: Dict[str, Any]) -> str:
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

        return f'# stub for action={action}\npass\n'
