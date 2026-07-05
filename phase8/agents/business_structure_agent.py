"""
BusinessStructureAgent (BSA) — 业务结构规划（Phase 8）

职责：读 InjectManifest → 产出 StructurePlan。禁止 diff。
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from agents.structure_plan import PlanUnit, StructurePlan, UnitKind
from federated_graph import FederatedInjectManifest

from phase4.multi_agent_router import AgentResult, Task


class BusinessStructureAgent:
    """Business Structure Agent — Plan 阶段 LLM 节点（demo 用 stub）"""

    name = "BusinessStructureAgent"

    def plan(
        self,
        task: Task,
        manifest: Optional[FederatedInjectManifest] = None,
    ) -> AgentResult:
        print(f"\n[{self.name}] 规划 StructurePlan...")
        constraints = task.context.get("manifest_constraints", [])
        patterns = task.context.get("manifest_patterns", [])
        constraint_ids = [c["id"] for c in constraints]
        pattern_ids = [p["id"] for p in patterns]

        # 模拟 struct 失败场景：首轮故意产出非法路径（重试后恢复正常）
        if task.context.get("_force_struct_fail") and not task.context.get("_struct_retry_done"):
            print("  [demo] 强制 struct 失败：Unit 路径不在白名单")
            plan = StructurePlan(
                plan_id=f"plan-{uuid.uuid4().hex[:6]}",
                action="apply_idempotency_pattern",
                rationale="demo struct fail",
                derived_from=constraint_ids[:3],
                units=[
                    PlanUnit(
                        unit_id="u1",
                        kind=UnitKind.MODIFY,
                        target_path="src/forbidden/service.py",
                        description="非法路径 demo",
                        constraint_ids=constraint_ids[:2],
                    ),
                ],
            )
            return AgentResult(status="completed", output=plan.to_dict())

        plan = StructurePlan(
            plan_id=f"plan-{uuid.uuid4().hex[:6]}",
            action="apply_idempotency_pattern",
            rationale="基于 ConstraintMemory + PatternMemory 拆分 Kafka 幂等改造",
            derived_from=constraint_ids[:4] + pattern_ids[:2],
            units=[
                PlanUnit(
                    unit_id="u1",
                    kind=UnitKind.MODIFY,
                    target_path="src/purchasing/procurement_service.py",
                    description="引入幂等消费：processed 集合 + session 去重",
                    pattern_ids=pattern_ids[:1],
                    constraint_ids=[c["id"] for c in constraints if c.get("rule_id")][:2],
                ),
                PlanUnit(
                    unit_id="u2",
                    kind=UnitKind.TEST,
                    target_path="tests/purchasing/test_idempotency.py",
                    description="幂等消费单测",
                    depends_on=["u1"],
                    constraint_ids=constraint_ids[:1],
                ),
            ],
        )
        print(f"  plan_id={plan.plan_id} units={len(plan.units)} action={plan.action}")
        for u in plan.units:
            print(f"    - {u.unit_id}: {u.target_path} ({u.kind.value})")
        return AgentResult(status="completed", output=plan.to_dict())
