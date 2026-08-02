"""
memory_actions — 校验后写入 / deprecated（骨架）

030 扩展：完整 GC、审计日志、与 schema_updater 级联
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from ontology_registry import OntologyRegistry, ValidationResult


def _dump_front_matter(meta: Dict[str, Any], body: str) -> str:
    fm = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{fm}\n---\n\n{body}\n"


class MemoryActions:
    def __init__(self, instances_root: Path, registry: OntologyRegistry):
        self.instances_root = instances_root
        self.registry = registry

    def write_memory(self, meta: Dict[str, Any], body: str) -> ValidationResult:
        meta.setdefault("status", "active")
        result = self.registry.validate(meta)
        if not result.ok:
            return result

        layer = meta.get("layer", "DOMAIN")
        layer_dir = self.instances_root / layer
        layer_dir.mkdir(parents=True, exist_ok=True)
        node_id = meta["id"]
        path = layer_dir / f"{node_id}.md"
        path.write_text(_dump_front_matter(meta, body), encoding="utf-8")
        print(f"  ✓ 写入记忆: {path}")
        return ValidationResult(True)

    def update_node(self, node, meta: Dict[str, Any], body: str | None = None) -> None:
        node.path.write_text(
            _dump_front_matter(meta, body if body is not None else node.body),
            encoding="utf-8",
        )

    def mark_deprecated(self, node, reason: str, migration_batch: str | None = None) -> None:
        meta = dict(node.meta)
        meta["status"] = "deprecated"
        meta["deprecated_reason"] = reason
        if migration_batch:
            meta["migration_batch"] = migration_batch
        self.update_node(node, meta, node.body)

    def deprecate_by_rule(self, rule_id: str, graph, migration_batch: str | None = None) -> int:
        """按规则级联标记 deprecated（不再使用 tier=archive 语义）"""
        count = 0
        for node in graph.find_active_by_rule(rule_id):
            self.mark_deprecated(
                node,
                reason=f"规则 {rule_id} 变更",
                migration_batch=migration_batch,
            )
            count += 1
        return count
