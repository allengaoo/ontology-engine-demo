"""
ep_promotion — EP 结束时的晋升门（Phase 8 P1）

Harness 侧确定性模块：决定 EP 产物哪些进共享记忆（Ontology），
哪些仅在 session 内保留/压缩后丢弃。

与 BackgroundTaskStore 的分工：
  - bg_store：EP 内 retry 缓冲（039）
  - ep_promotion：EP 边界 → writeback 清单（042）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from agents.structure_plan import StructurePlan
from harness.ep_coordinator import EPResult
from harness.verify_gate import VerifyOutcome, VerifyResult


class PromotionTarget(str, Enum):
    SHARED_DECISION = "shared_decision"       # DecisionRecord
    SHARED_PATTERN = "shared_pattern"         # PatternMemory（Plan 模板）
    SHARED_ANTI = "shared_anti"               # AntiPatternMemory（FAIL→热记忆）
    SESSION_ARCHIVE = "session_archive"       # 压缩日志，不进 Ontology
    DISCARD = "discard"                       # 直接丢弃


@dataclass
class PromotionItem:
    target: PromotionTarget
    reason: str
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PromotionPlan:
    ep_id: str
    status: str
    items: List[PromotionItem] = field(default_factory=list)

    def shared_items(self) -> List[PromotionItem]:
        return [
            i for i in self.items
            if i.target
            in (
                PromotionTarget.SHARED_DECISION,
                PromotionTarget.SHARED_PATTERN,
                PromotionTarget.SHARED_ANTI,
            )
        ]

    def summary(self) -> str:
        lines = [f"PromotionPlan ep={self.ep_id} status={self.status}"]
        for item in self.items:
            lines.append(f"  [{item.target.value}] {item.reason}")
        return "\n".join(lines)


# 默认晋升策略（与 042 文章策略表一致）
DEFAULT_PROMOTION_RULES = """
| EP 产物              | 去向              | 进下轮 inject |
|---------------------|-------------------|---------------|
| PASS + VerifyResult | DecisionRecord    | 是            |
| StructurePlan       | PatternMemory模板 | 是（pattern） |
| CA 完整代码         | 不进共享          | 否            |
| BSA/CA 原始对话     | 丢弃              | 否            |
| FAIL 详情(bg_store) | session 内用完即弃 | 否           |
"""


class EPPromotionGate:
    """EP PASS 后的晋升决策（零 LLM）。"""

    def plan_promotion(
        self,
        ep_result: EPResult,
        structure_plan: Optional[StructurePlan],
        verify_result: Optional[VerifyResult],
        memory_ids: List[str],
        bg_pending_count: int = 0,
    ) -> PromotionPlan:
        plan = PromotionPlan(ep_id=ep_result.ep_id, status=ep_result.status)
        items: List[PromotionItem] = []

        if ep_result.status != "completed":
            # FAIL → ANTI 热记忆（供下轮 inject；不走 DISCARD）
            fail_payload: Dict[str, Any] = {
                "ep_id": ep_result.ep_id,
                "status": ep_result.status,
            }
            if verify_result is not None:
                fail_payload.update(
                    {
                        "rule_id": verify_result.rule_id,
                        "detail": verify_result.detail,
                        "violations": list(verify_result.violations or [])[:20],
                        "command_output": (verify_result.command_output or "")[:2500],
                    }
                )
            else:
                # 从 verify turns 回填
                for t in reversed(ep_result.turns or []):
                    if t.phase.value == "verify" and t.rule_id:
                        fail_payload["rule_id"] = t.rule_id
                        fail_payload["detail"] = t.detail or ""
                        break
            items.append(PromotionItem(
                target=PromotionTarget.SHARED_ANTI,
                reason="EP FAIL → AntiPatternMemory（hot，暂不 GC）",
                payload=fail_payload,
            ))
            if bg_pending_count:
                items.append(PromotionItem(
                    target=PromotionTarget.SESSION_ARCHIVE,
                    reason=f"flush {bg_pending_count} 条 EP 内 retry 缓冲",
                ))
            plan.items = items
            return plan

        items.append(PromotionItem(
            target=PromotionTarget.SHARED_DECISION,
            reason="VerifyGate PASS → DecisionRecord",
            payload={
                "ep_id": ep_result.ep_id,
                "plan_id": structure_plan.plan_id if structure_plan else "",
                "units": [t.step_label for t in ep_result.turns if t.phase.value == "execute"],
                "derived_from": memory_ids,
                "rule_ids": [
                    t.rule_id for t in ep_result.turns
                    if t.rule_id and t.phase.value == "verify"
                ],
            },
        ))

        if structure_plan and structure_plan.units:
            items.append(PromotionItem(
                target=PromotionTarget.SHARED_PATTERN,
                reason="StructurePlan 可复用模板 → PatternMemory",
                payload={
                    "plan_id": structure_plan.plan_id,
                    "action": structure_plan.action,
                    "unit_count": len(structure_plan.units),
                    "unit_paths": [u.target_path for u in structure_plan.units],
                    "derived_from": structure_plan.derived_from,
                },
            ))

        items.append(PromotionItem(
            target=PromotionTarget.DISCARD,
            reason="CA 完整代码 diff 不写入共享层（仅 DEC 摘要）",
        ))
        items.append(PromotionItem(
            target=PromotionTarget.DISCARD,
            reason="Agent 原始对话 log 不晋升（避免污染 inject）",
        ))

        if bg_pending_count:
            items.append(PromotionItem(
                target=PromotionTarget.SESSION_ARCHIVE,
                reason=f"EP 结束 flush {bg_pending_count} 条 bg_store（不进共享）",
            ))

        plan.items = items
        return plan
