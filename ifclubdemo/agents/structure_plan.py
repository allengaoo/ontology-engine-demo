"""
structure_plan — BSA 输出的业务结构计划（Phase 8）

StructurePlan 是 Harness 与 CA 之间的契约：BSA 只产出 Plan，CA 按 Unit 执行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class UnitKind(str, Enum):
    CREATE = "create"
    MODIFY = "modify"
    TEST = "test"


@dataclass
class PlanUnit:
    unit_id: str
    kind: UnitKind
    target_path: str
    description: str
    depends_on: List[str] = field(default_factory=list)
    pattern_ids: List[str] = field(default_factory=list)
    constraint_ids: List[str] = field(default_factory=list)
    # 本 Unit 对外契约：函数/类型名列表，供后续 Unit 对齐
    exports: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "kind": self.kind.value,
            "target_path": self.target_path,
            "description": self.description,
            "depends_on": self.depends_on,
            "pattern_ids": self.pattern_ids,
            "constraint_ids": self.constraint_ids,
            "exports": self.exports,
        }


@dataclass
class StructurePlan:
    plan_id: str
    action: str
    units: List[PlanUnit]
    rationale: str = ""
    derived_from: List[str] = field(default_factory=list)

    def unit_order(self) -> List[PlanUnit]:
        """拓扑排序：依赖在前。"""
        by_id = {u.unit_id: u for u in self.units}
        visited: set = set()
        order: List[PlanUnit] = []

        def visit(uid: str) -> None:
            if uid in visited:
                return
            visited.add(uid)
            u = by_id.get(uid)
            if u is None:
                return
            for dep in u.depends_on:
                visit(dep)
            order.append(u)

        for u in self.units:
            visit(u.unit_id)
        return order

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "action": self.action,
            "rationale": self.rationale,
            "derived_from": self.derived_from,
            "units": [u.to_dict() for u in self.units],
        }
