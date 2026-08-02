"""
BusinessStructureAgent (BSA) — 业务结构规划（Phase 8）

有 LLM 时生成 StructurePlan；DEMOCODE_ALLOW_STUB=0 时禁止 stub。
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

IFCLUB_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(IFCLUB_ROOT))

from agents.coding_agent import allow_stub
from llm_chat import chat_json, format_manifest_for_prompt, is_llm_available

from agents.structure_plan import PlanUnit, StructurePlan, UnitKind
from federated_graph import FederatedInjectManifest

from core.task import AgentResult, Task


_BSA_SYSTEM = """你是 BusinessStructureAgent（BSA），只产出 StructurePlan JSON，禁止写代码。
输出：
{
  "plan_id": "plan-xxx",
  "action": "implement_feature",
  "rationale": "说明",
  "derived_from": ["记忆节点 id"],
  "units": [
    {
      "unit_id": "u1",
      "kind": "modify|create|test",
      "target_path": "backend/src/<app>/...",
      "description": "本 Unit 做什么",
      "exports": ["符号名"],
      "depends_on": [],
      "pattern_ids": [],
      "constraint_ids": []
    }
  ]
}

小模型友好硬规则（必须遵守）：
1) 每个 Unit 的 target_path 必须是具体文件（含扩展名），禁止目录伪 Unit
2) 默认只规划 1 个 Unit；任务正文显式点名多个文件时最多 2；禁止 3+
3) depends_on 必须为空列表（禁止把文件路径填进 depends_on）
4) 包名与任务一致：meeting_order 任务只用 backend/src/meeting_order/** 与 tests/meeting_order/**；
   oncall 任务只用 backend/src/oncall/** 与 tests/oncall/**
5) 禁止：backend/src/main.py、backend.src 前缀、backend/src/repositories/（缺包名）、
   跨包互引（meeting↔oncall）
6) 任务正文若点名具体文件，units 必须覆盖这些文件且不超过 max_units
7) exports 列出本文件对外符号，供后续对齐；不要规划「顺手改」无关文件
只输出 JSON。"""


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
        if plan is not None:
            print("  [LLM] StructurePlan 由大模型生成")
        elif allow_stub():
            print("  ⚠ 使用 StructurePlan stub（DEMOCODE_ALLOW_STUB=1）")
            plan = self._plan_stub(task)
        else:
            err = (
                "LLM StructurePlan 失败或不可用，且 stub 已禁用"
                "（DEMOCODE_ALLOW_STUB=1 可临时放开）"
            )
            print(f"  ✗ {err}")
            return AgentResult(status="failed", output={"error": err})

        print(f"  plan_id={plan.plan_id} units={len(plan.units)} action={plan.action}")
        for u in plan.units:
            print(f"    - {u.unit_id}: {u.target_path} ({u.kind.value})")
        return AgentResult(status="completed", output=plan.to_dict())

    def _plan_with_llm(self, task: Task) -> Optional[StructurePlan]:
        ctx = task.context or {}
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
            data = chat_json(_BSA_SYSTEM, "\n\n".join(parts), max_tokens=2048)
            if not data:
                return None
            return self._dict_to_plan(data)
        except Exception as exc:
            print(f"  ⚠ LLM StructurePlan 失败: {exc}")
            return None

    def _plan_stub(self, task: Task) -> StructurePlan:
        constraints = task.context.get("manifest_constraints", [])
        patterns = task.context.get("manifest_patterns", [])
        constraint_ids = [c["id"] for c in constraints]
        pattern_ids = [p["id"] for p in patterns]

        if task.context.get("_force_struct_fail") and not task.context.get(
            "_struct_retry_done"
        ):
            print("  [demo] 强制 struct 失败：Unit 路径不在白名单")
            return StructurePlan(
                plan_id=f"plan-{uuid.uuid4().hex[:6]}",
                action="demo_struct_fail",
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
            action="implement_oncall_conflict_check",
            rationale="基于记忆拆分 oncall 冲突检测",
            derived_from=constraint_ids[:4] + pattern_ids[:2],
            units=[
                PlanUnit(
                    unit_id="u1",
                    kind=UnitKind.MODIFY,
                    target_path="backend/src/oncall/domain/rules.py",
                    description="实现同日不可双班等冲突检测",
                    exports=["RuleViolation", "validate_roster", "check_no_double_shift"],
                    pattern_ids=pattern_ids[:1],
                    constraint_ids=[c["id"] for c in constraints if c.get("rule_id")][:2],
                ),
                PlanUnit(
                    unit_id="u2",
                    kind=UnitKind.TEST,
                    target_path="tests/oncall/test_rules.py",
                    description="冲突检测单测",
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
                exports=list(u.get("exports") or []),
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
