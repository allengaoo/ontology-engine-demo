"""
verify_gate — 三路判定：PASS / FAIL_IMPL / FAIL_STRUCT（Phase 8 Harness）

端侧场景：验证不依赖 LLM，纯 ConstraintMemory + arch_check。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from agents.coding_agent import UnitDiff
from code_validator import CodeValidator

from phase4.multi_agent_router import Task


class VerifyOutcome(str, Enum):
    PASS = "pass"
    FAIL_IMPL = "fail_impl"
    FAIL_STRUCT = "fail_struct"


@dataclass
class VerifyResult:
    outcome: VerifyOutcome
    rule_id: str = ""
    memory_id: str = ""
    detail: str = ""
    checks_run: int = 0
    violations: List[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.outcome == VerifyOutcome.PASS:
            return f"✓ PASS ({self.checks_run} checks)"
        return f"✗ {self.outcome.value.upper()} rule={self.rule_id} {self.detail}"


class VerifyGate:
    """Harness 侧确定性验证门。"""

    def verify(
        self,
        diffs: List[UnitDiff],
        task: Task,
        *,
        run_pytest_stub: bool = True,
    ) -> VerifyResult:
        graph = task.context.get("_code_arch_graph")
        if graph is None:
            return VerifyResult(outcome=VerifyOutcome.PASS, checks_run=0)

        validator = CodeValidator(graph)
        all_violations: List[str] = []
        checks = 0

        for diff in diffs:
            report = validator.validate(diff.code)
            checks += report.checks_run
            if not report.passed:
                for v in report.violations:
                    all_violations.append(f"[{diff.unit_id}] {v.detail}")
                    return VerifyResult(
                        outcome=VerifyOutcome.FAIL_IMPL,
                        rule_id=v.rule or "ARCH-001",
                        memory_id=v.memory_id,
                        detail=v.detail,
                        checks_run=checks,
                        violations=all_violations,
                    )

        if run_pytest_stub:
            checks += 1
            test_diffs = [d for d in diffs if d.target_path.startswith("tests/")]
            if test_diffs and not test_diffs[0].code.strip():
                return VerifyResult(
                    outcome=VerifyOutcome.FAIL_IMPL,
                    rule_id="TEST-001",
                    detail="测试文件为空",
                    checks_run=checks,
                )

        return VerifyResult(outcome=VerifyOutcome.PASS, checks_run=checks)
