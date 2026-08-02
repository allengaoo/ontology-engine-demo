"""
memory_prompt_builder — Memory Prompt 四段流水线（Phase 9）

① Intent      IntentRouter + AgentMemoryScope → domains / budget
② Retrieval   FederatedInjector（联邦 HybridSearch）
③ Compression 全局 token 上限二次裁剪（跨域，per-domain 预算之外的一层）
④ Manifest    FederatedInjectManifest + 可打印摘要

修复要点（Phase 9 反思）：
  - FederatedGraph.load() 每次 reload 生成全新 MemoryGraph；
    因此 build() 内**每次重建 FederatedInjector**，避免绑定到旧图（staleness）。
  - 检索前按域设置 schema 版本窗口，否则新写回（schema_version=2）被过滤。

Agent 只读 Manifest，不接触本模块的检索细节。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from agent_memory_scope import AgentMemoryScope
from federated_graph import (
    DomainConfig,
    FederatedGraph,
    FederatedInjectManifest,
    FederatedInjector,
    build_routed_domain_budgets,
)
from intent_router import IntentRouter


@dataclass
class PipelineStageAudit:
    """单段审计：命中数 / token / 备注。"""
    name: str
    hit_count: int = 0
    tokens: int = 0
    notes: str = ""


@dataclass
class PromptBuildResult:
    """流水线输出：Manifest + 四段审计。"""
    manifest: Optional[FederatedInjectManifest]
    memory_ids: List[str] = field(default_factory=list)
    stages: List[PipelineStageAudit] = field(default_factory=list)
    route_intent: str = ""
    route_domains: List[str] = field(default_factory=list)
    scope_name: str = ""
    dropped_ids: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"MemoryPromptBuilder scope={self.scope_name} "
            f"intent={self.route_intent} domains={self.route_domains}",
            f"  memory_ids={len(self.memory_ids)} tokens="
            f"{self.manifest.total_tokens if self.manifest else 0}",
        ]
        for s in self.stages:
            lines.append(
                f"  [{s.name}] hits={s.hit_count} tokens={s.tokens}"
                + (f" ({s.notes})" if s.notes else "")
            )
        return "\n".join(lines)

    def ep_writeback_ids(self) -> List[str]:
        return [
            mid for mid in self.memory_ids
            if mid.startswith("DEC-EP") or mid.startswith("BIZ-PAT-EP")
        ]


class MemoryPromptBuilder:
    """
    统一 inject 入口。替代 phase8 Coordinator 内散落的拼装逻辑。

    global_token_cap: 跨域全局上限；Compression 段据此丢弃最低优先节点。
                      None 表示不做全局裁剪（仅依赖 per-domain 预算）。
    """

    def __init__(
        self,
        fed_graph: FederatedGraph,
        domain_configs: List[DomainConfig],
        intent_router: Optional[IntentRouter] = None,
        *,
        global_token_cap: Optional[int] = None,
    ):
        self.fed_graph = fed_graph
        self.domain_configs = domain_configs
        self.intent_router = intent_router or IntentRouter()
        self.global_token_cap = global_token_cap

    def build(
        self,
        scope: AgentMemoryScope,
        task_description: str,
        keywords: Optional[List[str]] = None,
    ) -> PromptBuildResult:
        kws = list(keywords or [])
        stages: List[PipelineStageAudit] = []

        # 每次重建 injector：绑定到当前（可能刚 reload 的）图对象
        injector = FederatedInjector(self.fed_graph)
        self._apply_schema_windows(injector)

        # ① Intent
        route = self.intent_router.route(
            task_description, kws + scope.concept_hints
        )
        primary_domains = [
            d for d in scope.domains if d in route.domains
        ] or list(scope.domains)
        stages.append(PipelineStageAudit(
            name="Intent",
            hit_count=len(primary_domains),
            notes=f"intent={route.intent.value} budget×{scope.budget_multiplier}",
        ))

        # ② Retrieval（联邦检索；per-domain 预算在 injector 内执行）
        domain_budgets = build_routed_domain_budgets(
            self.domain_configs,
            route_domains=primary_domains,
            budget_multiplier=scope.budget_multiplier,
            auxiliary_multiplier=0.5,
        )
        search_kws = kws + scope.concept_hints + route.concept_hints
        manifest = injector.inject(
            task=task_description,
            keywords=search_kws,
            domain_budgets=domain_budgets,
            domains=scope.domains,
        )
        retrieved_ids = self._collect_memory_ids(manifest)
        stages.append(PipelineStageAudit(
            name="Retrieval",
            hit_count=len(retrieved_ids),
            tokens=manifest.total_tokens if manifest else 0,
            notes=f"keywords={len(search_kws)}",
        ))

        # ③ Compression — 跨域全局上限：超限丢弃最低优先（warm、靠后）节点
        dropped = self._apply_global_cap(manifest)
        memory_ids = self._collect_memory_ids(manifest)
        cap_note = (
            f"cap={self.global_token_cap} dropped={len(dropped)}"
            if self.global_token_cap is not None
            else "no global cap; per-domain budget only"
        )
        stages.append(PipelineStageAudit(
            name="Compression",
            hit_count=len(memory_ids),
            tokens=manifest.total_tokens if manifest else 0,
            notes=cap_note,
        ))

        # ④ Manifest
        stages.append(PipelineStageAudit(
            name="Manifest",
            hit_count=manifest.total_memories if manifest else 0,
            tokens=manifest.total_tokens if manifest else 0,
            notes="ready for Agent",
        ))

        return PromptBuildResult(
            manifest=manifest,
            memory_ids=memory_ids,
            stages=stages,
            route_intent=route.intent.value,
            route_domains=list(route.domains),
            scope_name=scope.agent_name,
            dropped_ids=dropped,
        )

    def _apply_schema_windows(self, injector: FederatedInjector) -> None:
        """按域当前 active 节点设置 schema 版本窗口（否则新写回被过滤）。"""
        for d_cfg in self.domain_configs:
            g = self.fed_graph.get_graph(d_cfg.name)
            if g is None:
                continue
            versions = sorted({
                n.schema_version for n in g.all_nodes()
                if n.status == "active"
            }) or [1]
            injector.set_schema_window(
                d_cfg.name,
                active_version=max(versions),
                compatible_versions=versions,
            )

    def _apply_global_cap(
        self, manifest: Optional[FederatedInjectManifest]
    ) -> List[str]:
        """
        全局 token 上限裁剪。per-domain 预算控制单域，此处控制跨域总量。

        原则（039）：hot / CRITICAL 约束**永不裁剪**，只从 warm 尾部丢弃。
        token 估算按各域 warm 均摊回收，够到上限即停。返回被丢弃 id。
        """
        if manifest is None or self.global_token_cap is None:
            return []
        if manifest.total_tokens <= self.global_token_cap:
            return []

        dropped: List[str] = []
        for dname, dm in manifest.domain_manifests.items():
            if manifest.total_tokens <= self.global_token_cap:
                break
            tier_tokens = getattr(dm, "tier_tokens", None) or {}
            warm_total = tier_tokens.get("warm", 0)
            warm_ids = self._warm_ids(dname, dm.memory_ids)
            if not warm_ids or warm_total <= 0:
                continue
            per = max(1, warm_total // max(1, len(warm_ids)))

            # 从尾部（检索靠后）丢 warm，直至到达上限或 warm 耗尽
            for drop_id in reversed(warm_ids):
                if manifest.total_tokens <= self.global_token_cap:
                    break
                dm.memory_ids.remove(drop_id)
                dropped.append(drop_id)
                warm_total = max(0, warm_total - per)
                tier_tokens["warm"] = warm_total
                dm.tier_tokens = tier_tokens
                dm.estimated_tokens = max(0, dm.estimated_tokens - per)
        return dropped

    def _warm_ids(self, domain: str, ids: List[str]) -> List[str]:
        """在指定域内，筛出 tier 非 hot 的节点 id（hot/CRITICAL 受保护）。"""
        g = self.fed_graph.get_graph(domain)
        if g is None:
            return []
        tier_by_id = {n.id: n.tier for n in g.all_nodes()}
        return [i for i in ids if tier_by_id.get(i, "warm") != "hot"]

    @staticmethod
    def _collect_memory_ids(manifest: Optional[FederatedInjectManifest]) -> List[str]:
        if manifest is None:
            return []
        ids: List[str] = []
        for dm in (manifest.domain_manifests or {}).values():
            ids.extend(list(getattr(dm, "memory_ids", None) or []))
        seen = set()
        out: List[str] = []
        for mid in ids:
            if mid not in seen:
                seen.add(mid)
                out.append(mid)
        return out
