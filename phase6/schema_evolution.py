"""
schema_evolution — 记忆 Schema 演进与迁移（031）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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


@dataclass
class SchemaSnapshot:
    version: int
    changed_rule: str
    created_at: str
    note: str = ""


@dataclass
class MigrationBatch:
    batch_id: str
    rule_id: str
    from_version: int
    to_version: int
    created: List[str] = field(default_factory=list)
    deprecated: List[str] = field(default_factory=list)
    rolled_back: bool = False

    def summary(self) -> str:
        state = "rolled_back" if self.rolled_back else "committed"
        return (
            f"{self.batch_id} rule={self.rule_id} {self.from_version}->{self.to_version} "
            f"created={len(self.created)} deprecated={len(self.deprecated)} state={state}"
        )


def create_snapshot(version: int, changed_rule: str, note: str = "") -> SchemaSnapshot:
    return SchemaSnapshot(
        version=version,
        changed_rule=changed_rule,
        created_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        note=note,
    )


def evolve_rule(
    graph: MemoryGraph,
    actions,
    rule_id: str,
    to_version: int,
) -> MigrationBatch:
    """
    规则演进：active 旧节点 -> deprecated，新节点 supersede 旧节点
    """
    now = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    batch = MigrationBatch(
        batch_id=f"mb-{rule_id}-{now}",
        rule_id=rule_id,
        from_version=max([n.schema_version for n in graph.find_by_rule(rule_id)] or [1]),
        to_version=to_version,
    )

    for node in graph.find_active_by_rule(rule_id):
        old_meta = dict(node.meta)
        old_id = old_meta["id"]

        new_meta = dict(old_meta)
        new_meta["id"] = f"{old_id}-v{to_version}"
        new_meta["schema_version"] = to_version
        new_meta["status"] = "active"
        new_meta["migration_batch"] = batch.batch_id
        new_meta.setdefault("derived_from", [])
        if old_id not in new_meta["derived_from"]:
            new_meta["derived_from"].append(old_id)
        new_meta.setdefault("supersedes", [])
        if old_id not in new_meta["supersedes"]:
            new_meta["supersedes"].append(old_id)

        write_result = actions.write_memory(new_meta, node.body)
        if write_result.ok:
            batch.created.append(new_meta["id"])

        actions.mark_deprecated(
            node,
            reason=f"schema_version 升级到 v{to_version}",
            migration_batch=batch.batch_id,
        )
        batch.deprecated.append(old_id)

    return batch


def rollback_batch(graph: MemoryGraph, actions, batch: MigrationBatch) -> MigrationBatch:
    """
    回滚演进批次：新建节点标记 rolled_back，旧节点恢复 active。
    """
    created_set = set(batch.created)
    deprecated_set = set(batch.deprecated)

    for node in graph.all_nodes():
        node_id = node.meta.get("id")
        if node_id in created_set:
            meta = dict(node.meta)
            meta["status"] = "rolled_back"
            meta["rolled_back_from"] = batch.batch_id
            actions.update_node(node, meta, node.body)
        elif node_id in deprecated_set:
            meta = dict(node.meta)
            meta["status"] = "active"
            meta["rollback_batch"] = batch.batch_id
            actions.update_node(node, meta, node.body)

    batch.rolled_back = True
    return batch
