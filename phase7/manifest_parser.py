"""
manifest_parser — 从 InjectManifest 解析 ConstraintMemory / PatternMemory（Phase 7 P1）

把联邦图里的真实记忆节点挂到 task.context，供 Agent 替代硬编码 CRITICAL/RULE。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from federated_graph import FederatedGraph, FederatedInjectManifest

from phase4.multi_agent_router import Task


def _summary_from_body(body: str, max_len: int = 120) -> str:
    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:max_len]
    return body.strip()[:max_len]


def parse_manifest_memories(
    fed_graph: FederatedGraph,
    manifest: FederatedInjectManifest,
) -> Dict[str, Any]:
    """按 manifest.memory_ids 从各域 MemoryGraph 解析结构化记忆。"""
    constraints: List[Dict[str, Any]] = []
    patterns: List[Dict[str, Any]] = []
    decisions: List[Dict[str, Any]] = []

    for domain, inj in manifest.domain_manifests.items():
        graph = fed_graph.get_graph(domain)
        if graph is None:
            continue
        for mid in inj.memory_ids:
            node = graph.get(mid)
            if node is None:
                continue
            base = {
                "id": node.id,
                "domain": domain,
                "title": node.meta.get("title", node.id),
                "layer": node.layer,
                "tier": node.tier,
                "how": _summary_from_body(node.body),
            }
            otype = node.object_type
            if otype == "ConstraintMemory":
                constraints.append({
                    **base,
                    "desc": node.meta.get("title", ""),
                    "rule_id": node.meta.get("rule_id"),
                    "enforcement": node.meta.get("enforcement"),
                })
            elif otype == "PatternMemory":
                patterns.append({
                    **base,
                    "about_concepts": node.meta.get("about_concepts", []),
                })
            elif otype == "DecisionRecord":
                decisions.append(base)

    return {
        "manifest_constraints": constraints,
        "manifest_patterns": patterns,
        "manifest_decisions": decisions,
    }


def enrich_task_from_manifest(
    task: Task,
    fed_graph: FederatedGraph,
    manifest: FederatedInjectManifest,
) -> None:
    """把解析结果写入 task.context（与 inject_manifest 并列）。"""
    task.context = task.context or {}
    parsed = parse_manifest_memories(fed_graph, manifest)
    task.context.update(parsed)

    # 兼容 OntologyAgent / SimAgent 旧字段名
    if parsed["manifest_constraints"]:
        task.context["critical_rules_from_manifest"] = parsed["manifest_constraints"]
