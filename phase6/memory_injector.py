"""
memory_injector — 记忆注入与 InjectManifest（模型透明接口）

对齐 Article 029 §3.3、016 压缩思想（骨架：段落提取，非 LLM 摘要）
Article 032: BudgetConfig — per-tier token 强制执行、inject_order 支持（记忆经济学）

设计选择：
  - BudgetConfig 从 injection_budget.yaml 加载，也可被实验脚本覆盖
  - 按 inject_order 依次处理各 tier，超出 tier_budget 时截断正文而非丢弃节点
  - tier_tokens 记录各层实际消耗，供实验对比
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

from hybrid_search import HybridSearch
from memory_graph import MemoryGraph, MemoryNode


# ---------------------------------------------------------------------------
# BudgetConfig — 记忆注入 token 预算策略
# ---------------------------------------------------------------------------

@dataclass
class BudgetConfig:
    """
    per-tier 注入预算配置。

    inject_order 决定节点出现在 context 中的顺序；
    hot 层永远应排在前面（CRITICAL 约束要求位置靠近 context 头部）。
    """
    total_budget_tokens: int = 2000
    hot: int = 400       # CRITICAL 约束，全量保障
    warm: int = 1000     # 任务相关，按检索排名截断
    cold: int = 0        # 背景历史，默认关闭
    reserve: int = 200   # 格式/分隔符缓冲，不分配给记忆内容
    compress_enabled: bool = True
    inject_order: List[str] = field(default_factory=lambda: ["hot", "warm", "cold"])

    @classmethod
    def from_dict(cls, d: dict) -> "BudgetConfig":
        tier = d.get("tier_budget", {})
        compress = d.get("compress", {})
        return cls(
            total_budget_tokens=d.get("total_budget_tokens", 2000),
            hot=tier.get("hot", 400),
            warm=tier.get("warm", 1000),
            cold=tier.get("cold", 0),
            reserve=tier.get("reserve", 200),
            compress_enabled=compress.get("enabled", True),
        )

    @property
    def content_budget(self) -> int:
        """可分配给记忆内容的 token 上限（扣除 reserve）"""
        return max(0, self.total_budget_tokens - self.reserve)

    def tier_limit(self, tier: str) -> int:
        return int(getattr(self, tier, 0))


# ---------------------------------------------------------------------------
# InjectManifest — 注入结果（透明接口）
# ---------------------------------------------------------------------------

@dataclass
class InjectManifest:
    task: str
    memory_ids: List[str] = field(default_factory=list)
    tiers: dict = field(default_factory=dict)        # tier -> count
    tier_tokens: dict = field(default_factory=dict)  # tier -> actual tokens
    estimated_tokens: int = 0
    context_text: str = ""

    def summary(self) -> str:
        tier_detail = " ".join(
            f"{k}≈{v}tk" for k, v in self.tier_tokens.items() if v > 0
        )
        base = (
            f"task={self.task!r} memories={len(self.memory_ids)} "
            f"tokens≈{self.estimated_tokens} ids={self.memory_ids}"
        )
        return base + (f" [{tier_detail}]" if tier_detail else "")


# ---------------------------------------------------------------------------
# MemoryInjector
# ---------------------------------------------------------------------------

class MemoryInjector:
    def __init__(self, graph: MemoryGraph, schema_root: Path):
        self.graph = graph
        self.schema_root = schema_root
        self._raw_budget = self._load_raw_budget()
        self._default_budget = BudgetConfig.from_dict(self._raw_budget)
        self.active_schema_version = 1
        self.compatible_schema_versions: List[int] = [1]

    def _load_raw_budget(self) -> dict:
        path = self.schema_root / "_config" / "injection_budget.yaml"
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def inject(
        self,
        task: str,
        keywords: List[str],
        budget: Optional[BudgetConfig] = None,
    ) -> InjectManifest:
        """
        按 budget.inject_order 依次注入各 tier 节点。

        每个 tier：
          - 超出 tier_budget 时截断节点正文（而非丢弃），保留 header 信息
          - 超出 content_budget（total - reserve）时跳过
        """
        if budget is None:
            budget = self._default_budget

        manifest = InjectManifest(task=task)
        sections: List[str] = []
        total_tokens_used = 0
        content_limit = budget.content_budget

        # 预先计算各 tier 候选节点
        search = HybridSearch(self.graph)
        warm_candidates = [
            n for n in search.search(keywords, limit=10)
            if n.tier != "hot" and self._is_injectable(n)
        ]
        cold_candidates = [
            n for n in self.graph.find_by_tier("cold")
            if self._is_injectable(n)
        ]

        for tier_name in budget.inject_order:
            tier_limit = budget.tier_limit(tier_name)
            if tier_limit <= 0:
                continue

            if tier_name == "hot":
                candidates = [
                    n for n in self.graph.find_by_tier("hot")
                    if self._is_injectable(n)
                ]
            elif tier_name == "warm":
                candidates = [
                    n for n in warm_candidates
                    if n.id not in manifest.memory_ids
                ]
            elif tier_name == "cold":
                candidates = [
                    n for n in cold_candidates
                    if n.id not in manifest.memory_ids
                ]
            else:
                continue

            tier_tokens_used = 0
            manifest.tiers[tier_name] = 0

            for node in candidates:
                body = self._compress_body(
                    node.body, node.object_type, budget.compress_enabled
                )
                block = self._format_node_with_body(node, body)
                block_tokens = self._estimate_tokens(block)

                # 超出 tier budget：尝试截断正文以适配剩余空间
                remaining_tier = tier_limit - tier_tokens_used
                if block_tokens > remaining_tier:
                    if remaining_tier < 25:
                        # 剩余空间不足以放置有意义的内容
                        continue
                    # 截断正文：粗估 1 token ≈ 2 汉字
                    max_body_chars = max(10, remaining_tier * 2)
                    body = body[:max_body_chars].rstrip() + "…[截断]"
                    block = self._format_node_with_body(node, body)
                    block_tokens = self._estimate_tokens(block)

                # 超出总内容预算：跳过
                if total_tokens_used + block_tokens > content_limit:
                    continue

                sections.append(block)
                manifest.memory_ids.append(node.id)
                manifest.tiers[tier_name] = manifest.tiers.get(tier_name, 0) + 1
                tier_tokens_used += block_tokens
                total_tokens_used += block_tokens

            manifest.tier_tokens[tier_name] = tier_tokens_used

        manifest.context_text = "\n\n---\n\n".join(sections)
        manifest.estimated_tokens = total_tokens_used
        return manifest

    def set_schema_window(
        self,
        active_version: int,
        compatible_versions: Optional[List[int]] = None,
    ) -> None:
        self.active_schema_version = active_version
        if compatible_versions is None:
            compatible_versions = [active_version]
        self.compatible_schema_versions = compatible_versions

    def _is_injectable(self, node: MemoryNode) -> bool:
        if node.status in {"deprecated", "superseded", "rolled_back"}:
            return False
        return node.schema_version in self.compatible_schema_versions

    def _format_node_with_body(self, node: MemoryNode, body: str) -> str:
        enforcement = node.meta.get("enforcement", "")
        enforcement_str = f" enforcement={enforcement}" if enforcement else ""
        header = (
            f"### [{node.id}] {node.meta.get('title', '')}\n"
            f"layer={node.layer} tier={node.tier} type={node.object_type}{enforcement_str}"
        )
        return f"{header}\n\n{body}"

    def _format_node(self, node: MemoryNode) -> str:
        """向后兼容接口，使用默认压缩配置"""
        body = self._compress_body(
            node.body, node.object_type, self._default_budget.compress_enabled
        )
        return self._format_node_with_body(node, body)

    def _compress_body(
        self, body: str, object_type: str, compress_enabled: bool = True
    ) -> str:
        cfg = self._raw_budget.get("compress", {})
        if not compress_enabled or not cfg.get("enabled", True):
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

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """粗估：1 token ≈ 2 汉字（保守）"""
        return max(1, len(text) // 2)
