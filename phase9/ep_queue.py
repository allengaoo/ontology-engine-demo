"""
ep_queue — 多 EP 串行编排（Phase 9）

职责：
  run_ep →（PASS）PromotionGate → MemoryEPWriteback → SessionFlush → reload
  → 下一 EP；FAIL 则熔断，不写 Shared，不启动依赖 EP。

不重写 Unit 状态机；Unit / VerifyGate 仍由 phase8 EPCoordinator 负责。

注：本文件放在 phase9/ 根目录，避免与 phase8/harness 包名冲突。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional

# 前置钩子：在每个 EP 真正 run 之前（含依赖检查通过、上游已 reload 后）触发，
# 供 demo 快照 Manifest、做跨 EP 差分。

from agents.structure_plan import PlanUnit, StructurePlan, UnitKind
from harness.ep_coordinator import EPCoordinator, EPResult
from harness.ep_promotion import EPPromotionGate, PromotionPlan
from harness.session_flush import SessionFlush
from memory_ep_writeback import MemoryEPWriteback
from phase4.multi_agent_router import Task


class QueueItemStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class EpQueueItem:
    ep_label: str
    task: Task
    keywords: List[str] = field(default_factory=list)
    depends_on: Optional[str] = None  # 依赖的 ep_label；上游 FAIL 则 skip
    status: QueueItemStatus = QueueItemStatus.PENDING
    ep_result: Optional[EPResult] = None
    promotion: Optional[PromotionPlan] = None
    written_ids: List[str] = field(default_factory=list)


@dataclass
class EpQueueResult:
    items: List[EpQueueItem] = field(default_factory=list)
    reloads: int = 0

    def summary(self) -> str:
        lines = [f"EpQueueResult reloads={self.reloads}"]
        for it in self.items:
            lines.append(
                f"  [{it.status.value}] {it.ep_label} "
                f"written={it.written_ids}"
            )
        return "\n".join(lines)


class EpQueue:
    """多 EP 串行队列。"""

    def __init__(
        self,
        coordinator: EPCoordinator,
        ep_writeback: MemoryEPWriteback,
        *,
        reload_fn: Optional[Callable[[], None]] = None,
        primary_domain: str = "code-arch",
    ):
        self.coordinator = coordinator
        self.ep_writeback = ep_writeback
        self.promotion_gate = EPPromotionGate()
        self.session_flush = SessionFlush(coordinator.bg_store)
        self.reload_fn = reload_fn
        self.primary_domain = primary_domain

    def run(
        self,
        items: List[EpQueueItem],
        *,
        dry_run: bool = False,
        pre_run_hook: Optional[Callable[[EpQueueItem], None]] = None,
    ) -> EpQueueResult:
        result = EpQueueResult(items=items)
        by_label = {it.ep_label: it for it in items}

        for item in items:
            if item.depends_on:
                upstream = by_label.get(item.depends_on)
                if upstream is None or upstream.status != QueueItemStatus.PASSED:
                    item.status = QueueItemStatus.SKIPPED
                    print(
                        f"\n[EpQueue] SKIP {item.ep_label} "
                        f"(upstream {item.depends_on} not PASSED)"
                    )
                    continue

            # 前置钩子：此时上游已 promote+reload，可快照本 EP 读到的 Manifest
            if pre_run_hook is not None:
                pre_run_hook(item)

            item.status = QueueItemStatus.RUNNING
            print(f"\n{'=' * 60}\n  [EpQueue] RUN {item.ep_label}\n{'=' * 60}")
            ep_result = self.coordinator.run_ep(
                item.task, keywords=item.keywords, dry_run=dry_run
            )
            item.ep_result = ep_result

            if ep_result.status != "completed":
                item.status = QueueItemStatus.FAILED
                print(f"[EpQueue] FAIL {item.ep_label} status={ep_result.status} → 熔断下游")
                self.session_flush.flush_ep_session(item.task)
                continue

            structure_plan = self._rebuild_plan(ep_result)
            mem_ids = self._memory_ids_from_result(ep_result, item.task)
            promotion = self.promotion_gate.plan_promotion(
                ep_result,
                structure_plan,
                verify_result=None,
                memory_ids=mem_ids,
                bg_pending_count=self.session_flush.pending_count,
            )
            item.promotion = promotion
            print(promotion.summary())

            written: List[str] = []
            for pitem in promotion.shared_items():
                nid = self.ep_writeback.apply_item(
                    pitem,
                    task_description=item.task.description,
                    primary_domain=self.primary_domain,
                    dry_run=dry_run,
                )
                if nid:
                    written.append(nid)
            item.written_ids = written

            archive = self.session_flush.compress_turns(ep_result.turns)
            self.session_flush.flush_ep_session(item.task)
            print(f"[SessionFlush] archive={archive[:80]}...")

            if self.reload_fn is not None:
                self.reload_fn()
                result.reloads += 1
                print("[EpQueue] reload 联邦图")

            item.status = QueueItemStatus.PASSED
            print(f"[EpQueue] PASS {item.ep_label} written={written}")

        return result

    @staticmethod
    def _rebuild_plan(ep_result: EPResult) -> Optional[StructurePlan]:
        exec_turns = [t for t in ep_result.turns if t.phase.value == "execute"]
        if not exec_turns:
            return None
        units = [
            PlanUnit(
                unit_id=t.step_label,
                kind=UnitKind.MODIFY,
                target_path=(
                    t.outcome.split("→")[-1].strip()
                    if "→" in t.outcome
                    else t.step_label
                ),
                description=t.outcome,
            )
            for t in exec_turns
        ]
        return StructurePlan(
            plan_id=f"plan-{ep_result.ep_id}",
            action="apply_idempotency_pattern",
            units=units,
            rationale="ep_queue rebuilt from execute turns",
        )

    @staticmethod
    def _memory_ids_from_result(ep_result: EPResult, task: Task) -> List[str]:
        for turn in reversed(ep_result.turns):
            if turn.memory_ids:
                return list(turn.memory_ids)
        ctx = task.context or {}
        ids = ctx.get("manifest_memory_ids") or []
        return list(ids) if isinstance(ids, list) else []
