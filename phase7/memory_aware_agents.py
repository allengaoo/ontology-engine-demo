"""
memory_aware_agents — 接收 InjectManifest 的 Agent 适配层（Phase 7 P0/P1）

不修改 Phase 4 核心逻辑，通过适配器把 FederatedInjectManifest 注入 task.context，
P1 起额外解析 ConstraintMemory / PatternMemory 供 Agent 读取。
"""

from __future__ import annotations

from typing import Any, List, Optional

from federated_graph import FederatedGraph, FederatedInjectManifest
from manifest_parser import enrich_task_from_manifest

from phase4.multi_agent_router import AgentResult, Task


def _attach_manifest(task: Task, manifest: Optional[FederatedInjectManifest]) -> None:
    if manifest is None:
        return
    task.context = task.context or {}
    all_ids: List[str] = []
    for m in manifest.domain_manifests.values():
        all_ids.extend(m.memory_ids)
    task.context["inject_manifest"] = {
        "total_memories": manifest.total_memories,
        "total_tokens": manifest.total_tokens,
        "memory_ids": all_ids,
        "domains": list(manifest.domain_manifests.keys()),
    }
    if manifest.context_text:
        task.context["memory_context_preview"] = manifest.context_text[:800]


class ManifestAwareAgent:
    """包装任意 Phase 4 Agent，execute 前挂载 manifest 并解析联邦记忆。"""

    def __init__(self, inner: Any, fed_graph: Optional[FederatedGraph] = None):
        self.inner = inner
        self.fed_graph = fed_graph
        self.name = inner.name

    def execute(
        self,
        task: Task,
        router,
        manifest: Optional[FederatedInjectManifest] = None,
    ) -> AgentResult:
        _attach_manifest(task, manifest)
        if manifest and self.fed_graph is not None:
            enrich_task_from_manifest(task, self.fed_graph, manifest)
            n_cn = len(task.context.get("manifest_constraints", []))
            n_pat = len(task.context.get("manifest_patterns", []))
            if n_cn or n_pat:
                print(f"  [manifest/parse] constraints={n_cn} patterns={n_pat}")
        elif manifest:
            print(
                f"  [manifest] memories={manifest.total_memories} "
                f"tokens≈{manifest.total_tokens} "
                f"domains={list(manifest.domain_manifests.keys())}"
            )
        return self.inner.execute(task, router)
