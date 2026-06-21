"""
memory_admin — 记忆控制平面管理接口（033）

MemoryAdmin 提供运维可见性与批量操作：
  - health_report()           健康快照（tier/type/status 分布）
  - audit_query()             条件筛查节点（status / gc_note 关键词）
  - bulk_deprecate_by_tier()  批量弃用指定 tier 的 active 节点
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from memory_graph import MemoryGraph, MemoryNode


@dataclass
class HealthReport:
    total: int = 0
    by_tier: Dict[str, int] = field(default_factory=dict)
    by_type: Dict[str, int] = field(default_factory=dict)
    by_status: Dict[str, int] = field(default_factory=dict)
    low_confidence: List[str] = field(default_factory=list)   # confidence < 0.5

    def summary(self) -> str:
        lines = [
            f"健康报告（共 {self.total} 条）",
            f"  Tier 分布: {self.by_tier}",
            f"  类型分布: {self.by_type}",
            f"  状态分布: {self.by_status}",
        ]
        if self.low_confidence:
            lines.append(f"  低置信度（<0.5）: {self.low_confidence}")
        return "\n".join(lines)


class MemoryAdmin:
    def __init__(self, graph: MemoryGraph):
        self.graph = graph

    # ── 健康报告 ────────────────────────────────────────────────
    def health_report(self) -> HealthReport:
        report = HealthReport(total=len(self.graph.nodes))
        by_tier: Dict[str, int] = defaultdict(int)
        by_type: Dict[str, int] = defaultdict(int)
        by_status: Dict[str, int] = defaultdict(int)
        low_confidence: List[str] = []

        for node in self.graph.all_nodes():
            by_tier[node.tier] += 1
            by_type[node.object_type] += 1
            by_status[node.status] += 1
            if node.confidence < 0.5:
                low_confidence.append(node.id)

        report.by_tier = dict(by_tier)
        report.by_type = dict(by_type)
        report.by_status = dict(by_status)
        report.low_confidence = sorted(low_confidence)
        return report

    # ── 审计查询 ────────────────────────────────────────────────
    def audit_query(
        self,
        status: Optional[str] = None,
        gc_note_contains: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> List[MemoryNode]:
        """按 status / gc_note / tier 过滤节点，用于审计"""
        results = []
        for node in self.graph.all_nodes():
            if status and node.status != status:
                continue
            if tier and node.tier != tier:
                continue
            if gc_note_contains:
                note = node.meta.get("gc_note", "") or ""
                if gc_note_contains not in note:
                    continue
            results.append(node)
        return results

    # ── 批量弃用 ────────────────────────────────────────────────
    def bulk_deprecate_by_tier(self, tier: str, actions, dry_run: bool = False) -> List[str]:
        """将指定 tier 的全部 active 节点批量标记 deprecated"""
        deprecated_ids = []
        for node in self.graph.find_by_tier(tier):
            if node.status == "active":
                if not dry_run:
                    actions.mark_deprecated(node, reason=f"admin_bulk: tier={tier}")
                deprecated_ids.append(node.id)
        return deprecated_ids
