"""
CodingAgent (CA) — 按 Unit 生成 diff（Phase 8）

职责：单 Unit fresh context → diff stub。禁止改 StructurePlan。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agents.structure_plan import PlanUnit, UnitKind
from code_validator import CodeValidator

from phase4.multi_agent_router import AgentResult, Task


@dataclass
class UnitDiff:
    unit_id: str
    target_path: str
    code: str
    lines: int = 0

    def __post_init__(self) -> None:
        self.lines = len(self.code.splitlines())


@dataclass
class CodingResult:
    diffs: List[UnitDiff] = field(default_factory=list)

    def all_code(self) -> str:
        return "\n\n".join(d.code for d in self.diffs)


class CodingAgent:
    """Coding Agent — Execute 阶段 LLM 节点（demo 用 stub）"""

    name = "CodingAgent"

    def execute_unit(
        self,
        unit: PlanUnit,
        task: Task,
        action: str = "",
    ) -> UnitDiff:
        print(f"\n[{self.name}] 执行 Unit {unit.unit_id}: {unit.target_path}")
        force_impl_fail = task.context.get("_force_impl_fail") and unit.unit_id == "u1"
        code = self._generate_code(unit, action, force_violation=force_impl_fail)
        print(f"  生成 diff stub：{len(code.splitlines())} 行")
        diff = UnitDiff(unit_id=unit.unit_id, target_path=unit.target_path, code=code)
        return diff

    def execute_unit_result(
        self,
        unit: PlanUnit,
        task: Task,
        action: str = "",
    ) -> AgentResult:
        diff = self.execute_unit(unit, task, action=action)
        return AgentResult(
            status="completed",
            output={"unit_id": diff.unit_id, "target_path": diff.target_path, "code": diff.code},
        )

    def validate_diffs(
        self,
        diffs: List[UnitDiff],
        task: Task,
    ) -> Optional[str]:
        """返回首个 violation detail，None 表示通过。"""
        graph = task.context.get("_code_arch_graph")
        if graph is None:
            return None
        validator = CodeValidator(graph)
        for diff in diffs:
            report = validator.validate(diff.code)
            print(f"  CodeValidator[{diff.unit_id}]: {report.summary()}")
            if not report.passed:
                v = report.violations[0]
                return f"{v.rule or v.memory_id}: {v.detail}"
        return None

    def _generate_code(
        self,
        unit: PlanUnit,
        action: str,
        force_violation: bool = False,
    ) -> str:
        if unit.kind == UnitKind.TEST:
            return '''\
"""test_idempotency — Kafka 幂等消费单测 stub"""
def test_duplicate_event_skipped():
    assert True
'''

        if force_violation:
            return '''\
"""procurement_service — 故意违反 ARCH-001 分层依赖"""
from infrastructure.kafka_producer import send_event

class ProcurementService:
    def handle_procurement_event(self, event_id: str, payload: dict) -> None:
        send_event(payload)
'''

        if action == "apply_idempotency_pattern" or "procurement" in unit.target_path:
            return '''\
"""procurement_service — Kafka 幂等消费 stub（Phase 8 demo）"""
from domain.repository import PurchaseOrderRepository

PROCESSED = set()

def handle_procurement_event(event_id: str, payload: dict) -> None:
    if event_id in PROCESSED:
        return
    repo = PurchaseOrderRepository()
    if repo.is_processed(event_id):
        return
    repo.create_order(payload)
    repo.mark_processed(event_id)
    PROCESSED.add(event_id)
'''

        return f"# stub for {unit.target_path}\npass\n"
