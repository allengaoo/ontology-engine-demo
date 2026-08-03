"""
atomicity_check — StructurePlan 原子性校验（Phase 8 Harness）

Harness 侧确定性检查：路径白名单、依赖环、Unit 粒度。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Set

from agents.structure_plan import StructurePlan


class CheckOutcome(str, Enum):
    PASS = "pass"
    FAIL_STRUCT = "fail_struct"


@dataclass
class AtomicityResult:
    outcome: CheckOutcome
    rule_id: str = ""
    detail: str = ""
    violations: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.outcome == CheckOutcome.PASS


DEFAULT_ALLOWED_PREFIXES = (
    "src/purchasing/",
    "tests/purchasing/",
    "src/domain/",
    "src/",
    "backend/",
    "frontend/src/",
    "tests/",
    "docs/",
    "data/",
)


class AtomicityCheck:
    """StructurePlan 原子性与路径白名单校验。"""

    def __init__(self, allowed_prefixes: Optional[tuple] = None):
        self.allowed_prefixes = allowed_prefixes or DEFAULT_ALLOWED_PREFIXES

    def check(self, plan: StructurePlan) -> AtomicityResult:
        violations: List[str] = []

        if not plan.units:
            violations.append("StructurePlan 无 Unit")

        unit_ids = {u.unit_id for u in plan.units}
        for u in plan.units:
            if not any(u.target_path.startswith(p) for p in self.allowed_prefixes):
                violations.append(
                    f"Unit {u.unit_id} 路径 {u.target_path} 不在白名单 {self.allowed_prefixes}"
                )
            for dep in u.depends_on:
                if dep not in unit_ids:
                    violations.append(f"Unit {u.unit_id} 依赖未知 Unit {dep}")

        cycle = self._detect_cycle(plan)
        if cycle:
            violations.append(f"Unit 依赖环：{' → '.join(cycle)}")

        if violations:
            return AtomicityResult(
                outcome=CheckOutcome.FAIL_STRUCT,
                rule_id="STRUCT-001",
                detail=violations[0],
                violations=violations,
            )
        return AtomicityResult(outcome=CheckOutcome.PASS)

    def _detect_cycle(self, plan: StructurePlan) -> Optional[List[str]]:
        graph = {u.unit_id: u.depends_on for u in plan.units}
        visited: Set[str] = set()
        stack: Set[str] = set()
        path: List[str] = []

        def dfs(node: str) -> Optional[List[str]]:
            if node in stack:
                idx = path.index(node)
                return path[idx:] + [node]
            if node in visited:
                return None
            visited.add(node)
            stack.add(node)
            path.append(node)
            for dep in graph.get(node, []):
                cyc = dfs(dep)
                if cyc:
                    return cyc
            path.pop()
            stack.remove(node)
            return None

        for uid in graph:
            cyc = dfs(uid)
            if cyc:
                return cyc
        return None
