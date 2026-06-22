"""
federated_graph — 双本体联邦（Article 033）

把多个 MemoryGraph（语义域）组合成一个可统一查询的联邦视图。

设计原则：
  - 每个域有独立的 instances 目录和可选的专用 Schema
  - 联邦查询保留 domain 来源标记，调用方可按域过滤
  - 跨域 Link（cross_domain_ref）允许一个域的记忆引用另一个域
  - FederatedInjector 支持 per-domain budget + 合并后的 InjectManifest

关键约束：
  - 域之间不共享 id 命名空间（BIZ-* vs CN-* 不冲突）
  - 域内 hot 约束永远比跨域 warm 记忆更早出现在 context 中
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from hybrid_search import HybridSearch
from memory_graph import MemoryGraph, MemoryNode
from memory_injector import BudgetConfig, InjectManifest, MemoryInjector
from ontology_registry import OntologyRegistry


# ---------------------------------------------------------------------------
# DomainConfig — 域声明
# ---------------------------------------------------------------------------

@dataclass
class DomainConfig:
    """单个语义域的配置"""
    name: str                            # 域名，如 "code-arch" / "purchasing"
    instances_root: Path                 # 实例目录
    schema_root: Path                    # Schema 根目录（可与其他域共享）
    budget: Optional[BudgetConfig] = None  # 域级 token 预算（None 则用全局默认）
    priority: int = 0                    # 数字越小越优先（0 = 最高）


# ---------------------------------------------------------------------------
# FederatedNode — 带域标记的记忆节点
# ---------------------------------------------------------------------------

@dataclass
class FederatedNode:
    node: MemoryNode
    domain: str

    # 代理属性，方便直接访问
    @property
    def id(self) -> str:
        return self.node.id

    @property
    def tier(self) -> str:
        return self.node.tier

    @property
    def layer(self) -> str:
        return self.node.layer

    @property
    def object_type(self) -> str:
        return self.node.object_type


# ---------------------------------------------------------------------------
# FederatedGraph — 多域图
# ---------------------------------------------------------------------------

class FederatedGraph:
    """
    把多个 MemoryGraph 联合为一个可统一查询的视图。

    load() 会分别加载每个域，并在共享的倒排索引中打上 domain 标记。
    """

    def __init__(self, domains: List[DomainConfig]):
        self.domains = domains
        self._graphs: Dict[str, MemoryGraph] = {}
        self._loaded = False

    def load(self) -> Dict[str, int]:
        """加载所有域，返回 {domain_name: node_count}"""
        counts: Dict[str, int] = {}
        for cfg in self.domains:
            registry = OntologyRegistry(cfg.schema_root)
            graph = MemoryGraph(cfg.instances_root, registry)
            n = graph.load()
            self._graphs[cfg.name] = graph
            counts[cfg.name] = n
        self._loaded = True
        return counts

    def get_graph(self, domain: str) -> Optional[MemoryGraph]:
        return self._graphs.get(domain)

    def all_nodes(self, domain: Optional[str] = None) -> List[FederatedNode]:
        """返回所有域（或指定域）的节点，附带 domain 标签"""
        result: List[FederatedNode] = []
        for d_cfg in self.domains:
            if domain and d_cfg.name != domain:
                continue
            g = self._graphs.get(d_cfg.name)
            if g:
                for n in g.all_nodes():
                    result.append(FederatedNode(node=n, domain=d_cfg.name))
        return result

    def find_by_tier(self, tier: str, domain: Optional[str] = None) -> List[FederatedNode]:
        results: List[FederatedNode] = []
        for d_cfg in self.domains:
            if domain and d_cfg.name != domain:
                continue
            g = self._graphs.get(d_cfg.name)
            if g:
                for n in g.find_by_tier(tier):
                    results.append(FederatedNode(node=n, domain=d_cfg.name))
        return results

    def search(self, keywords: List[str], limit: int = 10,
               domain: Optional[str] = None) -> List[FederatedNode]:
        """跨域 hybrid_search，按 tier + confidence 排序，保留域标记"""
        seen: set[str] = set()
        results: List[FederatedNode] = []

        for d_cfg in self.domains:
            if domain and d_cfg.name != domain:
                continue
            g = self._graphs.get(d_cfg.name)
            if not g:
                continue
            searcher = HybridSearch(g)
            for node in searcher.search(keywords, limit=limit):
                key = f"{d_cfg.name}:{node.id}"
                if key not in seen:
                    seen.add(key)
                    results.append(FederatedNode(node=node, domain=d_cfg.name))

        # 排序：hot > warm > cold，confidence 降序
        tier_order = {"hot": 0, "warm": 1, "cold": 2, "archive": 3}
        results.sort(key=lambda fn: (tier_order.get(fn.tier, 9), -fn.node.confidence))
        return results[:limit]

    def domain_count(self) -> int:
        return len(self._graphs)


# ---------------------------------------------------------------------------
# FederatedInjector — 联邦注入器
# ---------------------------------------------------------------------------

@dataclass
class FederatedInjectManifest:
    """联邦注入结果，包含各域的子 manifest"""
    task: str
    domain_manifests: Dict[str, InjectManifest] = field(default_factory=dict)
    cross_domain_ids: List[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(m.estimated_tokens for m in self.domain_manifests.values())

    @property
    def total_memories(self) -> int:
        return sum(len(m.memory_ids) for m in self.domain_manifests.values())

    @property
    def context_text(self) -> str:
        """合并所有域的 context，domain-priority 顺序"""
        parts: List[str] = []
        for domain, manifest in self.domain_manifests.items():
            if manifest.context_text:
                parts.append(f"<!-- domain={domain} -->\n{manifest.context_text}")
        return "\n\n===\n\n".join(parts)

    def summary(self) -> str:
        domain_detail = "  ".join(
            f"{d}:memories={len(m.memory_ids)},tokens≈{m.estimated_tokens}"
            for d, m in self.domain_manifests.items()
        )
        return (
            f"task={self.task!r} total_memories={self.total_memories} "
            f"total_tokens≈{self.total_tokens}\n    [{domain_detail}]"
        )


def build_routed_domain_budgets(
    domain_configs: List[DomainConfig],
    route_domains: List[str],
    budget_multiplier: float,
    auxiliary_multiplier: float = 0.5,
) -> Dict[str, BudgetConfig]:
    """
    根据 IntentRouter 的路由决策，为各域生成缩放后的 BudgetConfig。

    - route_domains 内的域：budget_multiplier
    - 其余域（辅助域）：auxiliary_multiplier（默认 0.5）
    """
    result: Dict[str, BudgetConfig] = {}
    for d_cfg in domain_configs:
        base = d_cfg.budget or BudgetConfig()
        mult = budget_multiplier if d_cfg.name in route_domains else auxiliary_multiplier
        result[d_cfg.name] = base.scaled(mult)
    return result


class FederatedInjector:
    """
    从 FederatedGraph 中按域独立注入，合并为 FederatedInjectManifest。

    注入顺序：domains 列表的 priority 顺序（priority 小的先注入）。
    每个域内：hot 先于 warm（由 BudgetConfig.inject_order 控制）。
    """

    def __init__(self, fed_graph: FederatedGraph):
        self.fed_graph = fed_graph
        # 为每个域建立独立的 MemoryInjector
        self._injectors: Dict[str, MemoryInjector] = {}
        for d_cfg in fed_graph.domains:
            g = fed_graph.get_graph(d_cfg.name)
            if g:
                injector = MemoryInjector(g, d_cfg.schema_root)
                self._injectors[d_cfg.name] = injector

    def inject(
        self,
        task: str,
        keywords: List[str],
        domain_budgets: Optional[Dict[str, BudgetConfig]] = None,
        domains: Optional[List[str]] = None,
    ) -> FederatedInjectManifest:
        """
        按域独立注入，返回联邦 manifest。

        domain_budgets: 可以为每个域指定不同的 BudgetConfig；
                        未指定时使用域的 DomainConfig.budget 或默认值。
        domains:        若指定，只注入列表内的域；None 表示注入全部已加载域。
        """
        fed_manifest = FederatedInjectManifest(task=task)
        allowed = set(domains) if domains else None

        # 按 priority 排序，priority 小的域先处理（其 hot 内容先出现在 context 中）
        ordered_domains = sorted(self.fed_graph.domains, key=lambda d: d.priority)

        for d_cfg in ordered_domains:
            if allowed is not None and d_cfg.name not in allowed:
                continue
            injector = self._injectors.get(d_cfg.name)
            if not injector:
                continue

            # 选取预算：调用方 override > 域配置 > 默认
            budget: Optional[BudgetConfig] = None
            if domain_budgets and d_cfg.name in domain_budgets:
                budget = domain_budgets[d_cfg.name]
            elif d_cfg.budget:
                budget = d_cfg.budget

            manifest = injector.inject(task, keywords, budget=budget)
            fed_manifest.domain_manifests[d_cfg.name] = manifest

        return fed_manifest

    def set_schema_window(
        self,
        domain: str,
        active_version: int,
        compatible_versions: Optional[List[int]] = None,
    ) -> None:
        """为指定域设置 Schema 版本窗口"""
        injector = self._injectors.get(domain)
        if injector:
            injector.set_schema_window(active_version, compatible_versions)
