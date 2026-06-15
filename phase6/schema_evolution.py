"""
schema_evolution — Schema 健康度报告（骨架，030 扩展）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from memory_graph import MemoryGraph, MemoryNode


@dataclass
class EvolutionReport:
    total_nodes: int = 0
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> str:
        return f"节点数={self.total_nodes} 警告={len(self.warnings)}"


def analyze_graph(graph: MemoryGraph) -> EvolutionReport:
    report = EvolutionReport(total_nodes=len(graph.nodes))
    for node in graph.all_nodes():
        if node.object_type == "PatternMemory":
            if not node.meta.get("solution") and "HOW" not in node.body:
                report.warnings.append(f"{node.id}: Pattern 缺少 solution/HOW")
        if node.tier == "hot" and node.confidence < 0.5:
            report.warnings.append(f"{node.id}: hot 记忆 confidence 过低")
    return report
