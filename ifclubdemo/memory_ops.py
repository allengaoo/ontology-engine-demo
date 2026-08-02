"""
memory_ops — Phase 9 / 045：把记忆治理挂到 EP 队列节奏上

043 让读侧可审计，044 让血统一跳可见。045 关注另一个问题：
队列跑起来后，health / GC / reload 什么时候跑？

钩子：
  - after_reload_health：每次 reload 后读取健康快照；
  - queue_idle_gc：队列空闲 / EP 结束时跑 GC（可 dry-run 或落盘）；
  - age_idle_decay：每次空闲对 warm 写回做轻度衰减，驱动冷热切换；
  - assert_no_low_confidence_hot：防止低质量 hot 继续进入 Manifest。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from federated_graph import FederatedGraph
from memory_actions import MemoryActions
from memory_admin import HealthReport, MemoryAdmin
from memory_gc import GCPolicy, MemoryGC, GCReport


@dataclass
class OpsSnapshot:
    domain: str
    total: int
    by_tier: Dict[str, int]
    by_status: Dict[str, int]
    low_confidence: List[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.domain}: total={self.total} "
            f"tier={self.by_tier} status={self.by_status} "
            f"low_conf={self.low_confidence}"
        )


@dataclass
class QueueOpsReport:
    health: List[OpsSnapshot] = field(default_factory=list)
    gc: Dict[str, GCReport] = field(default_factory=dict)
    aged: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = ["QueueMemoryOps:"]
        for h in self.health:
            lines.append(f"  [health] {h.summary()}")
        for domain, report in self.gc.items():
            lines.append(
                f"  [gc:{domain}] decay={len(report.decayed)} "
                f"degrade={len(report.degraded)} clean={len(report.cleaned)}"
            )
        for domain, n in self.aged.items():
            lines.append(f"  [age:{domain}] touched={n}")
        for w in self.warnings:
            lines.append(f"  [warn] {w}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "health": [
                {
                    "domain": h.domain,
                    "total": h.total,
                    "by_tier": h.by_tier,
                    "by_status": h.by_status,
                    "low_confidence": h.low_confidence,
                }
                for h in self.health
            ],
            "gc": {
                d: {
                    "decayed": r.decayed,
                    "degraded": r.degraded,
                    "cleaned": r.cleaned,
                }
                for d, r in self.gc.items()
            },
            "aged": self.aged,
            "warnings": self.warnings,
        }


class QueueMemoryOps:
    """EP 队列后的轻量治理面。"""

    def __init__(
        self,
        fed_graph: FederatedGraph,
        actions_by_domain: Dict[str, MemoryActions],
        *,
        gc_dry_run: bool = True,
        age_step: float = 0.0,
    ):
        self.fed_graph = fed_graph
        self.actions_by_domain = actions_by_domain
        self.gc_dry_run = gc_dry_run
        self.age_step = age_step

    def after_reload_health(self) -> List[OpsSnapshot]:
        snapshots: List[OpsSnapshot] = []
        for d_cfg in self.fed_graph.domains:
            graph = self.fed_graph.get_graph(d_cfg.name)
            if graph is None:
                continue
            report: HealthReport = MemoryAdmin(graph).health_report()
            snapshots.append(OpsSnapshot(
                domain=d_cfg.name,
                total=report.total,
                by_tier=report.by_tier,
                by_status=report.by_status,
                low_confidence=report.low_confidence,
            ))
        return snapshots

    def age_idle_decay(self) -> Dict[str, int]:
        """
        每次空闲对「EP 写回类」warm 节点做轻度置信度衰减，
        以便后续 GC 能触发 warm→cold→archived（演示冷热切换）。
        """
        touched: Dict[str, int] = {}
        if self.age_step <= 0:
            return touched
        for d_cfg in self.fed_graph.domains:
            graph = self.fed_graph.get_graph(d_cfg.name)
            actions = self.actions_by_domain.get(d_cfg.name)
            if graph is None or actions is None:
                continue
            n = 0
            for node in graph.all_nodes():
                if node.status != "active":
                    continue
                if node.tier not in ("hot", "warm"):
                    continue
                oid = node.id or ""
                tags = node.tags or []
                # FAIL→ANTI 热记忆与显式保护节点不衰减
                if (
                    oid.startswith("ANTI-EP-")
                    or node.meta.get("gc_protect")
                    or "gc-protect" in tags
                ):
                    continue
                # 只衰减会话/EP 写回，不动 inject 种子约束
                if not (
                    oid.startswith("DEC-")
                    or oid.startswith("BIZ-PAT-EP")
                    or "ep-" in oid.lower()
                    or "agent-output" in tags
                ):
                    continue
                new_conf = round(max(0.0, float(node.confidence) - self.age_step), 3)
                if abs(new_conf - node.confidence) < 1e-9:
                    continue
                if not self.gc_dry_run:
                    meta = dict(node.meta)
                    meta["confidence"] = new_conf
                    note = meta.get("gc_note", "") or ""
                    meta["gc_note"] = (
                        f"{note}; age_idle_decay -{self.age_step}→{new_conf}".strip("; ")
                    )
                    actions.update_node(node, meta, node.body)
                n += 1
            touched[d_cfg.name] = n
        return touched

    def queue_idle_gc(self, *, dry_run: Optional[bool] = None) -> Dict[str, GCReport]:
        reports: Dict[str, GCReport] = {}
        use_dry = self.gc_dry_run if dry_run is None else dry_run
        for d_cfg in self.fed_graph.domains:
            graph = self.fed_graph.get_graph(d_cfg.name)
            actions = self.actions_by_domain.get(d_cfg.name)
            if graph is None or actions is None:
                continue
            reports[d_cfg.name] = MemoryGC(
                graph,
                GCPolicy(dry_run=use_dry),
            ).run_gc(actions)
        return reports

    def run_after_ep_idle(self) -> QueueOpsReport:
        """单个 EP 结束后的空闲钩子：age → GC → health。"""
        report = QueueOpsReport()
        report.aged = self.age_idle_decay()
        # age 后若落盘，需让图侧看到新 confidence：由调用方 reload；
        # 这里仍基于当前图跑 GC（同一次内存视图）。
        report.gc = self.queue_idle_gc()
        report.health = self.after_reload_health()
        for h in report.health:
            if h.low_confidence and h.by_tier.get("hot", 0):
                report.warnings.append(
                    f"{h.domain}: low-confidence nodes exist while hot tier is active"
                )
        return report

    def run_after_queue(self) -> QueueOpsReport:
        """整队结束后再跑一轮（与 idle 相同，便于汇总）。"""
        return self.run_after_ep_idle()
