"""
hybrid_search — 图优先检索 + 关键词降级

对齐 Article 029 §1.2 / 015 检索流程（骨架）
"""

from __future__ import annotations

from typing import List

from memory_graph import MemoryGraph, MemoryNode


class HybridSearch:
    def __init__(self, graph: MemoryGraph, min_graph_results: int = 1):
        self.graph = graph
        self.min_graph_results = min_graph_results

    def search(self, keywords: List[str], limit: int = 10) -> List[MemoryNode]:
        seen: set[str] = set()
        results: List[MemoryNode] = []

        for kw in keywords:
            for node in self.graph.find_by_concept(kw):
                if node.id not in seen:
                    seen.add(node.id)
                    results.append(node)

        if len(results) >= self.min_graph_results:
            return self._rank(results)[:limit]

        # 关键词降级：标题子串
        for node in self.graph.all_nodes():
            title = node.meta.get("title", "")
            for kw in keywords:
                if kw.lower() in title.lower() and node.id not in seen:
                    seen.add(node.id)
                    results.append(node)

        return self._rank(results)[:limit]

    def _rank(self, nodes: List[MemoryNode]) -> List[MemoryNode]:
        tier_order = {"hot": 0, "warm": 1, "cold": 2, "archive": 3}
        return sorted(
            nodes,
            key=lambda n: (tier_order.get(n.tier, 9), -n.confidence),
        )
