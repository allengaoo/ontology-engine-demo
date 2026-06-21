"""
memory_gc — 记忆垃圾回收（033）

三种 GC 策略：
  1. confidence_decay   — 置信度低于阈值进一步衰减
  2. tier_degrade       — warm/cold 节点按 confidence 降级
  3. stale_cleanup      — 已被 supersede 且无活跃引用的 deprecated 节点标记 evicted
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from memory_graph import MemoryGraph, MemoryNode


@dataclass
class GCPolicy:
    # confidence_decay：低于此值触发衰减
    decay_below: float = 0.7
    # 单次衰减步长
    decay_step: float = 0.1
    # warm → cold 触发阈值
    cold_below: float = 0.5
    # cold → archived 触发阈值
    archive_below: float = 0.3
    # 是否执行 deprecated stale 清理
    enable_stale_cleanup: bool = True
    # dry_run：True 时只记录不写文件
    dry_run: bool = False


@dataclass
class GCReport:
    decayed: List[Tuple[str, float, float]] = field(default_factory=list)       # (id, old_conf, new_conf)
    degraded: List[Tuple[str, str, str]] = field(default_factory=list)          # (id, from_tier, to_tier)
    cleaned: List[str] = field(default_factory=list)                            # stale deprecated evicted

    def summary(self) -> str:
        lines = ["GC 报告:"]
        lines.append(f"  置信度衰减: {len(self.decayed)} 条")
        for node_id, old_c, new_c in self.decayed:
            lines.append(f"    {node_id}: {old_c} → {new_c}")
        lines.append(f"  Tier 降级:   {len(self.degraded)} 条")
        for node_id, ft, tt in self.degraded:
            lines.append(f"    {node_id}: {ft} → {tt}")
        lines.append(f"  废弃版本清理: {len(self.cleaned)} 条")
        for node_id in self.cleaned:
            lines.append(f"    {node_id}: deprecated → evicted")
        return "\n".join(lines)


class MemoryGC:
    def __init__(self, graph: MemoryGraph, policy: GCPolicy | None = None):
        self.graph = graph
        self.policy = policy or GCPolicy()

    def run_gc(self, actions) -> GCReport:
        report = GCReport()
        self._decay_confidence(actions, report)
        self._degrade_tiers(actions, report)
        if self.policy.enable_stale_cleanup:
            self._stale_cleanup(actions, report)
        return report

    # ── 策略 1: 置信度衰减 ────────────────────────────────────────
    def _decay_confidence(self, actions, report: GCReport) -> None:
        for node in self.graph.all_nodes():
            if node.status != "active":
                continue
            if node.confidence < self.policy.decay_below:
                new_conf = round(max(0.0, node.confidence - self.policy.decay_step), 3)
                if not self.policy.dry_run:
                    meta = dict(node.meta)
                    meta["confidence"] = new_conf
                    meta["gc_note"] = f"confidence_decay: {node.confidence}→{new_conf}"
                    actions.update_node(node, meta, node.body)
                report.decayed.append((node.id, node.confidence, new_conf))

    # ── 策略 2: tier 降级 ──────────────────────────────────────────
    def _degrade_tiers(self, actions, report: GCReport) -> None:
        tier_rules: List[Tuple[str, float, str]] = [
            ("warm", self.policy.cold_below, "cold"),
            ("cold", self.policy.archive_below, "archived"),
        ]
        for from_tier, threshold, to_tier in tier_rules:
            for node in self.graph.find_by_tier(from_tier):
                if node.status != "active":
                    continue
                if node.confidence < threshold:
                    if not self.policy.dry_run:
                        meta = dict(node.meta)
                        meta["tier"] = to_tier
                        meta["gc_note"] = (
                            f"tier_degrade: {from_tier}→{to_tier}"
                            f" (confidence={node.confidence})"
                        )
                        actions.update_node(node, meta, node.body)
                    report.degraded.append((node.id, from_tier, to_tier))

    # ── 策略 3: stale deprecated 清理 ─────────────────────────────
    def _stale_cleanup(self, actions, report: GCReport) -> None:
        """
        deprecated 且已被更新版本 supersede 的节点 → evicted

        判断条件：
          - status == deprecated
          - meta 中有 migration_batch（说明被批量升级替换）
          - 存在至少一个 superseding 节点处于 active 状态
        """
        active_ids = {n.id for n in self.graph.all_nodes() if n.status == "active"}

        for node in self.graph.all_nodes():
            if node.status != "deprecated":
                continue
            if not node.meta.get("migration_batch"):
                continue
            # 检查是否存在 supersede 当前节点的 active 节点
            superseded_by_active = any(
                node.id in (n.meta.get("supersedes", []) or [])
                for n in self.graph.all_nodes()
                if n.id in active_ids
            )
            if superseded_by_active:
                if not self.policy.dry_run:
                    meta = dict(node.meta)
                    meta["status"] = "evicted"
                    meta["gc_note"] = "stale_cleanup: superseded by active version"
                    actions.update_node(node, meta, node.body)
                report.cleaned.append(node.id)
