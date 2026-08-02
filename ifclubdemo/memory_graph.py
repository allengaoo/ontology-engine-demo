"""
MemoryGraph — 加载 instances/*.md，构建概念反向索引

职责（Article 029 §1.2）：
  - 解析 YAML front-matter + Markdown 正文
  - _concept_to_ids：about_concepts → memory id
  - find_by_rule(rule_id) → 级联 deprecated 入口（030 扩展）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ontology_registry import OntologyRegistry, ValidationResult


_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


@dataclass
class MemoryNode:
    id: str
    meta: Dict[str, Any]
    body: str
    path: Path

    @property
    def tier(self) -> str:
        return self.meta.get("tier", "warm")

    @property
    def layer(self) -> str:
        return self.meta.get("layer", "")

    @property
    def object_type(self) -> str:
        return self.meta.get("object_type", "")

    @property
    def confidence(self) -> float:
        return float(self.meta.get("confidence", 1.0))

    @property
    def status(self) -> str:
        return self.meta.get("status", "active")

    @property
    def schema_version(self) -> int:
        return int(self.meta.get("schema_version", 1))

    @property
    def tags(self) -> List[str]:
        return list(self.meta.get("tags", []))


class MemoryGraph:
    def __init__(self, instances_root: Path, registry: OntologyRegistry):
        self.instances_root = instances_root
        self.registry = registry
        self.nodes: Dict[str, MemoryNode] = {}
        self._concept_to_ids: Dict[str, List[str]] = {}
        self._rule_to_ids: Dict[str, List[str]] = {}

    def load(self) -> int:
        """加载全部实例；返回节点数"""
        self.nodes.clear()
        self._concept_to_ids.clear()
        self._rule_to_ids.clear()

        for path in sorted(self.instances_root.rglob("*.md")):
            node = self._parse_file(path)
            if node is None:
                continue
            result = self.registry.validate(node.meta)
            if not result.ok:
                print(f"  ⚠ 跳过无效实例 {path.name}: {result.errors}")
                continue
            self.nodes[node.id] = node
            self._index_node(node)

        return len(self.nodes)

    def _parse_file(self, path: Path) -> Optional[MemoryNode]:
        text = path.read_text(encoding="utf-8")
        m = _FRONT_MATTER_RE.match(text)
        if not m:
            return None
        meta = yaml.safe_load(m.group(1)) or {}
        body = m.group(2).strip()
        node_id = meta.get("id") or path.stem
        return MemoryNode(id=node_id, meta=meta, body=body, path=path)

    def _index_node(self, node: MemoryNode) -> None:
        for concept in node.meta.get("about_concepts", []) or []:
            key = concept.lower()
            self._concept_to_ids.setdefault(key, []).append(node.id)
        for rule_id in node.meta.get("about_rules", []) or []:
            self._rule_to_ids.setdefault(rule_id, []).append(node.id)

    def get(self, node_id: str) -> Optional[MemoryNode]:
        return self.nodes.get(node_id)

    def all_nodes(self) -> List[MemoryNode]:
        return list(self.nodes.values())

    def find_by_tier(self, tier: str) -> List[MemoryNode]:
        return [n for n in self.nodes.values() if n.tier == tier]

    def find_by_concept(self, keyword: str) -> List[MemoryNode]:
        key = keyword.lower()
        ids = set(self._concept_to_ids.get(key, []))
        # tags 子串兜底
        for n in self.nodes.values():
            for tag in n.tags:
                if key in tag.lower():
                    ids.add(n.id)
        return [self.nodes[i] for i in ids if i in self.nodes]

    def find_by_rule(self, rule_id: str) -> List[MemoryNode]:
        ids = self._rule_to_ids.get(rule_id, [])
        return [self.nodes[i] for i in ids if i in self.nodes]

    def find_active_by_rule(self, rule_id: str) -> List[MemoryNode]:
        return [n for n in self.find_by_rule(rule_id) if n.status == "active"]
