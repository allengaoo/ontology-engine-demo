"""
BusinessStructureAgent (BSA) — 业务结构规划（Phase 8）

有 LLM_API_KEY 时由大模型生成 StructurePlan；否则 stub。
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

DEMOCODE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(DEMOCODE_ROOT))

from llm_chat import chat_json, format_manifest_for_prompt, is_llm_available  # noqa: E402

from agents.structure_plan import PlanUnit, StructurePlan, UnitKind
from federated_graph import FederatedInjectManifest

from phase4.multi_agent_router import AgentResult, Task


_BSA_SYSTEM = """你是 BusinessStructureAgent（BSA），只产出业务结构计划 StructurePlan，禁止写具体代码 diff。
输出 JSON：
{
  "plan_id": "plan-xxx",
  "action": "apply_idempotency_pattern",
  "rationale": "说明",
  "derived_from": ["记忆节点 id"],
  "units": [
    {
      "unit_id": "u1",
      "kind": "modify|create|test",
      "target_path": "src/purchasing/... 或 tests/purchasing/...",
      "description": "本 Unit 做什么",
      "depends_on": [],
      "pattern_ids": [],
      "constraint_ids": []
    }
  ]
}
路径必须在 src/purchasing/ 或 tests/purchasing/ 下。只输出 JSON。"""


class BusinessStructureAgent:
    """Business Structure Agent — Plan 阶段"""

    name = "BusinessStructureAgent"

    def plan(
        self,
        task: Task,
        manifest: Optional[FederatedInjectManifest] = None,
    ) -> AgentResult:
        print(f"\n[{self.name}] 规划 StructurePlan...")

        plan = self._plan_with_llm(task)
        if plan is None:
            plan = self._plan_stub(task)
        else:
            print("  [LLM] StructurePlan 由大模型生成")

        print(f"  plan_id={plan.plan_id} units={len(plan.units)} action={plan.action}")
        for u in plan.units:
            print(f"    - {u.unit_id}: {u.target_path} ({u.kind.value})")
        return AgentResult(status="completed", output=plan.to_dict())

    def _plan_with_llm(self, task: Task) -> Optional[StructurePlan]:
        ctx = task.context or {}
        feedback = ctx.get("_struct_feedback") or ctx.get("_struct_retry_done")
        parts = [
            f"任务：{task.description}",
            f"InjectManifest：\n{format_manifest_for_prompt(ctx)}",
        ]
        if ctx.get("_struct_feedback"):
            parts.append(f"上轮 AtomicityCheck 失败，须修正：{ctx['_struct_feedback']}")
        bg = ctx.get("_bg_results", [])
        if bg:
            parts.append(f"后台反馈：{bg[-1].get('result')}")

        try:
            data = chat_json(_BSA_SYSTEM, "\n\n".join(parts), max_tokens=1536)
            if not data:
                return None
            return self._dict_to_plan(data)
        except Exception as exc:
            print(f"  ⚠ LLM StructurePlan 失败，fallback stub: {exc}")
            return None

    def _plan_stub(self, task: Task) -> StructurePlan:
        constraints = task.context.get("manifest_constraints", [])
        patterns = task.context.get("manifest_patterns", [])
        constraint_ids = [c["id"] for c in constraints]
        pattern_ids = [p["id"] for p in patterns]

        if task.context.get("_force_struct_fail") and not task.context.get("_struct_retry_done"):
            print("  [demo] 强制 struct 失败：Unit 路径不在白名单")
            return StructurePlan(
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

        return StructurePlan(
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

    @staticmethod
    def _dict_to_plan(data: dict) -> StructurePlan:
        units = [
            PlanUnit(
                unit_id=u["unit_id"],
                kind=UnitKind(u["kind"]),
                target_path=u["target_path"],
                description=u.get("description", ""),
                depends_on=u.get("depends_on", []),
                pattern_ids=u.get("pattern_ids", []),
                constraint_ids=u.get("constraint_ids", []),
            )
            for u in data.get("units", [])
        ]
        return StructurePlan(
            plan_id=data.get("plan_id") or f"plan-{uuid.uuid4().hex[:6]}",
            action=data.get("action", ""),
            units=units,
            rationale=data.get("rationale", ""),
            derived_from=data.get("derived_from", []),
        )
