"""
memory_ops — Phase 9 / 045：把记忆治理挂到 EP 队列节奏上

043 让读侧可审计，044 让血统一跳可见。045 关注另一个问题：
队列跑起来后，health / GC / reload 什么时候跑？

这里不引入后台服务，只做三个确定性钩子：
  - after_reload_health：每次 reload 后读取健康快照；
  - queue_idle_gc：队列空闲时跑 GC dry-run；
  - assert_no_low_confidence_hot：防止低质量 hot 继续进入 Manifest。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

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
        for w in self.warnings:
            lines.append(f"  [warn] {w}")
        return "\n".join(lines)


class QueueMemoryOps:
    """EP 队列后的轻量治理面。"""

    def __init__(self, fed_graph: FederatedGraph, actions_by_domain: Dict[str, MemoryActions]):
        self.fed_graph = fed_graph
        self.actions_by_domain = actions_by_domain

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

    def queue_idle_gc(self) -> Dict[str, GCReport]:
        reports: Dict[str, GCReport] = {}
        for d_cfg in self.fed_graph.domains:
            graph = self.fed_graph.get_graph(d_cfg.name)
            actions = self.actions_by_domain.get(d_cfg.name)
            if graph is None or actions is None:
                continue
            reports[d_cfg.name] = MemoryGC(
                graph,
                GCPolicy(dry_run=True),
            ).run_gc(actions)
        return reports

    def run_after_queue(self) -> QueueOpsReport:
        report = QueueOpsReport()
        report.health = self.after_reload_health()
        report.gc = self.queue_idle_gc()
        for h in report.health:
            # hot 低置信度是高风险：会靠前注入，又不一定可靠。
            if h.low_confidence and h.by_tier.get("hot", 0):
                report.warnings.append(
                    f"{h.domain}: low-confidence nodes exist while hot tier is active"
                )
        return report
