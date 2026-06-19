"""
memory_injector — 记忆注入与 InjectManifest（模型透明接口）

对齐 Article 029 §3.3、016 压缩思想（骨架：段落提取，非 LLM 摘要）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml

from hybrid_search import HybridSearch
from memory_graph import MemoryGraph, MemoryNode


@dataclass
class InjectManifest:
    task: str
    memory_ids: List[str] = field(default_factory=list)
    tiers: dict = field(default_factory=dict)
    estimated_tokens: int = 0
    context_text: str = ""

    def summary(self) -> str:
        return (
            f"task={self.task!r} memories={len(self.memory_ids)} "
            f"tokens≈{self.estimated_tokens} ids={self.memory_ids}"
        )


class MemoryInjector:
    def __init__(self, graph: MemoryGraph, schema_root: Path):
        self.graph = graph
        self.schema_root = schema_root
        self._budget = self._load_budget()
        self.active_schema_version = 1
        self.compatible_schema_versions: List[int] = [1]

    def _load_budget(self) -> dict:
        path = self.schema_root / "_config" / "injection_budget.yaml"
        if not path.exists():
            return {"total_budget_tokens": 2000, "tier_budget": {}}
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def inject(self, task: str, keywords: List[str]) -> InjectManifest:
        manifest = InjectManifest(task=task)
        sections: List[str] = []
        total_chars = 0

        # Rule: tier=hot 全量注入
        hot_nodes = [
            n for n in self.graph.find_by_tier("hot")
            if self._is_injectable(n)
        ]
        manifest.tiers["hot"] = len(hot_nodes)
        for node in hot_nodes:
            block = self._format_node(node)
            sections.append(block)
            manifest.memory_ids.append(node.id)
            total_chars += len(block)

        # warm：图检索
        search = HybridSearch(self.graph)
        warm_nodes = [
            n for n in search.search(keywords, limit=5)
            if n.tier != "hot" and self._is_injectable(n)
        ]
        manifest.tiers["warm"] = len(warm_nodes)
        for node in warm_nodes:
            if node.id in manifest.memory_ids:
                continue
            block = self._format_node(node)
            sections.append(block)
            manifest.memory_ids.append(node.id)
            total_chars += len(block)

        manifest.context_text = "\n\n---\n\n".join(sections)
        manifest.estimated_tokens = max(1, total_chars // 2)  # 粗估中文 token
        return manifest

    def set_schema_window(self, active_version: int, compatible_versions: List[int] | None = None) -> None:
        self.active_schema_version = active_version
        if compatible_versions is None:
            compatible_versions = [active_version]
        self.compatible_schema_versions = compatible_versions

    def _is_injectable(self, node: MemoryNode) -> bool:
        if node.status in {"deprecated", "superseded", "rolled_back"}:
            return False
        return node.schema_version in self.compatible_schema_versions

    def _format_node(self, node: MemoryNode) -> str:
        header = (
            f"### [{node.id}] {node.meta.get('title', '')}\n"
            f"layer={node.layer} tier={node.tier} type={node.object_type}"
        )
        body = self._compress_body(node.body, node.object_type)
        return f"{header}\n\n{body}"

    def _compress_body(self, body: str, object_type: str) -> str:
        cfg = self._budget.get("compress", {})
        if not cfg.get("enabled", True):
            return body[:2000]

        headers = cfg.get("segment_headers", ["## HOW", "## WHEN"])
        if object_type == "DecisionRecord":
            headers = ["## 背景", "## 决策", "## 备选"]

        parts: List[str] = []
        for h in headers:
            if h in body:
                start = body.index(h)
                end = body.find("\n## ", start + 1)
                chunk = body[start:end] if end != -1 else body[start:]
                parts.append(chunk.strip())
        return "\n\n".join(parts) if parts else body[:500]
