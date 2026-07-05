"""
CodingAgent (CA) — 按 Unit 生成 diff（Phase 8）

有 LLM_API_KEY 时由大模型生成代码；否则 stub。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

DEMOCODE_ROOT = Path(__file__).resolve().parent.parent.parent
PHASE6 = DEMOCODE_ROOT / "phase6"
sys.path.insert(0, str(PHASE6))
sys.path.insert(0, str(DEMOCODE_ROOT))

from agents.structure_plan import PlanUnit, UnitKind
from code_validator import CodeValidator
from llm_chat import chat_complete, format_manifest_for_prompt, is_llm_available  # noqa: E402

from phase4.multi_agent_router import AgentResult, Task


_CA_SYSTEM = """你是 CodingAgent（CA），只为单个 Unit 生成 Python 源码（不是 diff 格式，是完整文件内容）。
要求：
- 只输出纯 Python 代码，不要 markdown
- 路径在 src/purchasing/ 或 tests/purchasing/
- 领域层不得 import infrastructure/adapter/kafka_producer（ARCH-001）
- 遵守 InjectManifest 中 enforcement=reject 的 ConstraintMemory"""


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
    """Coding Agent — Execute 阶段"""

    name = "CodingAgent"

    def execute_unit(
        self,
        unit: PlanUnit,
        task: Task,
        action: str = "",
    ) -> UnitDiff:
        print(f"\n[{self.name}] 执行 Unit {unit.unit_id}: {unit.target_path}")
        force_impl_fail = task.context.get("_force_impl_fail") and unit.unit_id == "u1"
        if force_impl_fail and not is_llm_available():
            code = self._generate_code_stub(unit, action, force_violation=True)
        else:
            code = self._generate_with_llm(unit, task, action, force_impl_fail)
            if code is None:
                code = self._generate_code_stub(unit, action, force_violation=force_impl_fail)
            else:
                print("  [LLM] 代码由大模型生成")

        print(f"  生成代码：{len(code.splitlines())} 行")
        return UnitDiff(unit_id=unit.unit_id, target_path=unit.target_path, code=code)

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

    def _generate_with_llm(
        self,
        unit: PlanUnit,
        task: Task,
        action: str,
        force_violation: bool,
    ) -> Optional[str]:
        if force_violation:
            return None
        ctx = task.context or {}
        bg = ctx.get("_bg_results", [])
        verify_hint = ""
        if bg:
            verify_hint = f"\nVerifyGate 上轮失败（须修正）：{bg[-1].get('result')}"

        user = (
            f"任务：{task.description}\n"
            f"StructurePlan action：{action}\n"
            f"本 Unit：{unit.to_dict() if hasattr(unit, 'to_dict') else unit}\n"
            f"目标路径：{unit.target_path}\n"
            f"ConstraintMemory：\n{format_manifest_for_prompt(ctx)}"
            f"{verify_hint}"
        )
        try:
            raw = chat_complete(_CA_SYSTEM, user, max_tokens=2048)
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

    def validate_diffs(
        self,
        diffs: List[UnitDiff],
        task: Task,
    ) -> Optional[str]:
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

    def _generate_code_stub(
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
