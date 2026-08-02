"""
ep_queue — 多 EP 串行编排（Phase 9）

职责：
  run_ep →（PASS）PromotionGate → MemoryEPWriteback → SessionFlush
  → queue_idle_gc → reload → 下一 EP；
  FAIL 则熔断共享写回，但仍 flush 会话记忆并跑空闲 GC。

不重写 Unit 状态机；Unit / VerifyGate 仍由 phase8 EPCoordinator 负责。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from agents.structure_plan import PlanUnit, StructurePlan, UnitKind
from harness.ep_coordinator import EPCoordinator, EPResult
from harness.ep_promotion import EPPromotionGate, PromotionPlan
from harness.freeze_state import add_frozen_prefixes, load_frozen_prefixes
from harness.session_flush import SessionFlush
from harness.verify_gate import VerifyOutcome, VerifyResult
from memory_ep_writeback import MemoryEPWriteback
from memory_ops import QueueMemoryOps, QueueOpsReport
from core.task import Task


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
    ops_reports: List[Dict[str, Any]] = field(default_factory=list)
    final_ops: Optional[QueueOpsReport] = None

    def summary(self) -> str:
        lines = [f"EpQueueResult reloads={self.reloads} idle_ops={len(self.ops_reports)}"]
        for it in self.items:
            lines.append(
                f"  [{it.status.value}] {it.ep_label} "
                f"written={it.written_ids}"
            )
        if self.final_ops:
            lines.append(self.final_ops.summary())
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
        memory_ops: Optional[QueueMemoryOps] = None,
        session_id: str = "",
    ):
        self.coordinator = coordinator
        self.ep_writeback = ep_writeback
        self.promotion_gate = EPPromotionGate()
        self.session_flush = SessionFlush(
            coordinator.bg_store,
            workspace_root=coordinator.workspace_root,
        )
        self.reload_fn = reload_fn
        self.primary_domain = primary_domain
        self.memory_ops = memory_ops
        self.session_id = session_id

    def run(
        self,
        items: List[EpQueueItem],
        *,
        dry_run: bool = False,
        pre_run_hook: Optional[Callable[[EpQueueItem], None]] = None,
        fuse_on_fail: bool = True,
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

            # 会话 id 写入 task.context，供归档区分共享/会话
            item.task.context = item.task.context or {}
            if self.session_id:
                item.task.context["_session_id"] = self.session_id
            # 加载 workspace freeze → task + Atomicity/DiffApplier
            frozen = load_frozen_prefixes(self.coordinator.workspace_root)
            item.task.context["_frozen_prefixes"] = frozen
            self.coordinator.atomicity.set_frozen_prefixes(frozen)
            self.coordinator.applier.set_frozen_prefixes(frozen)

            if pre_run_hook is not None:
                pre_run_hook(item)

            item.status = QueueItemStatus.RUNNING
            print(f"\n{'=' * 60}\n  [EpQueue] RUN {item.ep_label}\n{'=' * 60}")
            ep_result = self.coordinator.run_ep(
                item.task, keywords=item.keywords, dry_run=dry_run
            )
            item.ep_result = ep_result

            written: List[str] = []
            promotion: Optional[PromotionPlan] = None

            if ep_result.status != "completed":
                item.status = QueueItemStatus.FAILED
                print(f"[EpQueue] FAIL {item.ep_label} status={ep_result.status}")
                verify_result = self._verify_from_task(item.task, ep_result)
                promotion = self.promotion_gate.plan_promotion(
                    ep_result,
                    None,
                    verify_result=verify_result,
                    memory_ids=[],
                    bg_pending_count=self.session_flush.pending_count,
                )
                item.promotion = promotion
                print(promotion.summary())
                # FAIL → ANTI 热记忆写回
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
                print(f"[EpQueue] FAIL shared_anti_written={written}")
            else:
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
                item.status = QueueItemStatus.PASSED
                print(f"[EpQueue] PASS {item.ep_label} shared_written={written}")

                # PASS 后可选 freeze（分层稳定点）
                freeze_after = item.task.context.get("_freeze_after") or []
                if freeze_after and not dry_run:
                    new_frozen = add_frozen_prefixes(
                        self.coordinator.workspace_root, freeze_after
                    )
                    print(f"[EpQueue] freeze updated → {new_frozen}")
                    self.coordinator.atomicity.set_frozen_prefixes(new_frozen)
                    self.coordinator.applier.set_frozen_prefixes(new_frozen)

            # 会话记忆归档（不进 Ontology）
            sid = self.session_id or item.task.context.get("_session_id", "default")
            arch_path = self.session_flush.archive_ep(
                session_id=sid,
                ep_id=ep_result.ep_id,
                ep_label=item.ep_label,
                task_description=item.task.description,
                status=item.status.value,
                turns=ep_result.turns,
                promotion_summary=promotion.summary() if promotion else "",
                shared_written=written,
            )
            flushed = self.session_flush.flush_ep_session(item.task)
            print(
                f"[SessionFlush] session={sid} flushed_bg={flushed} "
                f"archive={arch_path}"
            )

            # EP 空闲：age + GC + health
            if self.memory_ops is not None:
                ops = self.memory_ops.run_after_ep_idle()
                result.ops_reports.append(
                    {"ep_label": item.ep_label, "ops": ops.to_dict()}
                )
                print(ops.summary())

            if self.reload_fn is not None:
                self.reload_fn()
                result.reloads += 1
                print("[EpQueue] reload 联邦图")

            if item.status == QueueItemStatus.FAILED and fuse_on_fail:
                print(f"[EpQueue] 熔断下游（fuse_on_fail=True）")
                # 标记后续依赖项在循环中 skip；无 depends_on 的仍继续
                continue

        if self.memory_ops is not None:
            result.final_ops = self.memory_ops.run_after_queue()
            print("\n[EpQueue] final ops\n" + result.final_ops.summary())
            if self.reload_fn is not None:
                self.reload_fn()
                result.reloads += 1

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

    @staticmethod
    def _verify_from_task(task: Task, ep_result: EPResult) -> Optional[VerifyResult]:
        outcome = (
            VerifyOutcome.FAIL_STRUCT
            if ep_result.status == "failed_struct"
            else VerifyOutcome.FAIL_IMPL
        )
        fb = (task.context or {}).get("_last_verify_feedback") or {}
        if fb:
            return VerifyResult(
                outcome=outcome,
                rule_id=str(fb.get("rule_id") or ""),
                detail=str(fb.get("detail") or ""),
                violations=list(fb.get("violations") or []),
                command_output=str(fb.get("command_output") or ""),
            )
        for t in reversed(ep_result.turns or []):
            if t.phase.value == "verify" and t.rule_id:
                return VerifyResult(
                    outcome=outcome,
                    rule_id=t.rule_id or "",
                    detail=t.detail or "",
                )
        return None
