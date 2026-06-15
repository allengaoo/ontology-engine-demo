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
    return f"---\n{fm}---\n\n{body}\n"


class MemoryActions:
    def __init__(self, instances_root: Path, registry: OntologyRegistry):
        self.instances_root = instances_root
        self.registry = registry

    def write_memory(self, meta: Dict[str, Any], body: str) -> ValidationResult:
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

    def deprecate_by_rule(self, rule_id: str, graph) -> int:
        """骨架：标记 meta 中 tier=archive（030 改为 status 字段）"""
        count = 0
        for node in graph.find_by_rule(rule_id):
            node.meta["tier"] = "archive"
            node.meta["deprecated_reason"] = f"规则 {rule_id} 变更"
            path = node.path
            path.write_text(
                _dump_front_matter(node.meta, node.body),
                encoding="utf-8",
            )
            count += 1
        return count
