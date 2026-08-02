"""
lineage_expander — Phase 9 / 044：把 derived_from 从字段变成检索一跳

Promotion Gate 写回 DecisionRecord 时会保留 derived_from。043 只证明
EP-2 能检索到 DEC；044 继续验证：DEC 指向的来源记忆也能按预算进入
Manifest 的候选集。

原则：
  - 只扩 1 跳，避免图遍历爆炸；
  - hot / ConstraintMemory 优先；
  - 扩展结果只补 ids 与审计，不让 Agent 自行遍历图。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from federated_graph import FederatedGraph
from memory_graph import MemoryNode
from memory_prompt_builder import PromptBuildResult


@dataclass
class LineageExpansionResult:
    seed_ids: List[str] = field(default_factory=list)
    added_ids: List[str] = field(default_factory=list)
    already_present: List[str] = field(default_factory=list)
    missing_ids: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "LineageExpansion:",
            f"  seeds={self.seed_ids}",
            f"  added={self.added_ids}",
            f"  already_present={self.already_present}",
            f"  missing={self.missing_ids}",
        ]
        return "\n".join(lines)


class LineageExpander:
    """沿 DecisionRecord / PatternMemory 的 derived_from 扩一跳。"""

    def __init__(self, fed_graph: FederatedGraph):
        self.fed_graph = fed_graph

    def expand(
        self,
        build_result: PromptBuildResult,
        *,
        seed_prefixes: Optional[List[str]] = None,
        max_added: int = 4,
    ) -> LineageExpansionResult:
        seed_prefixes = seed_prefixes or ["DEC-EP", "BIZ-PAT-EP"]
        present = set(build_result.memory_ids)
        result = LineageExpansionResult()

        for seed_id in build_result.memory_ids:
            if not any(seed_id.startswith(p) for p in seed_prefixes):
                continue
            seed = self._find_node(seed_id)
            if seed is None:
                result.missing_ids.append(seed_id)
                continue
            result.seed_ids.append(seed_id)
            for parent_id in self._derived_from(seed):
                if parent_id in present:
                    result.already_present.append(parent_id)
                    continue
                parent = self._find_node(parent_id)
                if parent is None:
                    result.missing_ids.append(parent_id)
                    continue
                result.added_ids.append(parent_id)
                present.add(parent_id)
                if len(result.added_ids) >= max_added:
                    return self._dedupe(result)

        return self._dedupe(result)

    def _find_node(self, node_id: str) -> Optional[MemoryNode]:
        for d_cfg in self.fed_graph.domains:
            graph = self.fed_graph.get_graph(d_cfg.name)
            if graph is None:
                continue
            node = graph.get(node_id)
            if node is not None:
                return node
        return None

    @staticmethod
    def _derived_from(node: MemoryNode) -> List[str]:
        raw = node.meta.get("derived_from") or []
        if isinstance(raw, str):
            return [raw]
        return [str(x) for x in raw]

    @staticmethod
    def _dedupe(result: LineageExpansionResult) -> LineageExpansionResult:
        for attr in ("seed_ids", "added_ids", "already_present", "missing_ids"):
            seen = set()
            out = []
            for item in getattr(result, attr):
                if item not in seen:
                    seen.add(item)
                    out.append(item)
            setattr(result, attr, out)
        return result
