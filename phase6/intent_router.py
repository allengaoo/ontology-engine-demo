"""
intent_router — 意图分类 + 记忆路由（Article 034）

核心洞见：调度即查询
  路由器不决定"执行什么"，而是决定"从哪里拿记忆"。
  意图分类的结果直接映射为查询参数（域 / tier / 概念词 / 预算倍数）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ── 意图类型 ──────────────────────────────────────────────────────
class IntentType(str, Enum):
    ARCHITECTURE   = "architecture"    # 系统设计、技术选型
    PURCHASING     = "purchasing"      # 采购、供应商、合规
    DEBUGGING      = "debugging"       # 排错、异常分析
    DOCUMENTATION  = "documentation"  # 写文档、规范
    GENERAL        = "general"         # 兜底


# 每种意图的触发关键词（中英双语）
_INTENT_KEYWORDS: Dict[IntentType, List[str]] = {
    IntentType.ARCHITECTURE: [
        "架构", "设计", "分层", "模块", "接口", "服务", "schema", "本体",
        "architecture", "design", "layer", "module",
    ],
    IntentType.PURCHASING: [
        "采购", "供应商", "预算", "合规", "报价", "合同", "vendor",
        "procurement", "compliance", "sourcing",
    ],
    IntentType.DEBUGGING: [
        "报错", "bug", "exception", "异常", "失败", "crash", "排错",
        "定位", "error", "traceback", "fix",
    ],
    IntentType.DOCUMENTATION: [
        "文档", "规范", "readme", "注释", "说明", "记录",
        "document", "spec", "comment",
    ],
}


# ── 路由配置 ──────────────────────────────────────────────────────
@dataclass
class RouteConfig:
    intent: IntentType
    domains: List[str]           # 查询哪些语义域
    tiers: List[str]             # 包含哪些 tier
    concept_hints: List[str]     # 额外注入检索词
    budget_multiplier: float = 1.0   # 相对于基准 budget 的倍数

    def __str__(self) -> str:
        return (
            f"意图={self.intent.value} "
            f"域={self.domains} "
            f"tier={self.tiers} "
            f"budget×{self.budget_multiplier}"
        )


# 路由表：intent → RouteConfig 模板
_DEFAULT_ROUTE_TABLE: Dict[IntentType, RouteConfig] = {
    IntentType.ARCHITECTURE: RouteConfig(
        intent=IntentType.ARCHITECTURE,
        domains=["code-arch"],
        tiers=["hot", "warm"],
        concept_hints=["architecture", "pattern", "layer"],
        budget_multiplier=1.2,
    ),
    IntentType.PURCHASING: RouteConfig(
        intent=IntentType.PURCHASING,
        domains=["purchasing"],
        tiers=["hot", "warm", "cold"],
        concept_hints=["vendor", "compliance", "procurement"],
        budget_multiplier=0.8,
    ),
    IntentType.DEBUGGING: RouteConfig(
        intent=IntentType.DEBUGGING,
        domains=["code-arch"],
        tiers=["hot"],
        concept_hints=["debugging", "error", "fix"],
        budget_multiplier=0.6,
    ),
    IntentType.DOCUMENTATION: RouteConfig(
        intent=IntentType.DOCUMENTATION,
        domains=["code-arch"],
        tiers=["warm", "cold"],
        concept_hints=["documentation", "standard"],
        budget_multiplier=0.9,
    ),
    IntentType.GENERAL: RouteConfig(
        intent=IntentType.GENERAL,
        domains=["code-arch"],
        tiers=["hot", "warm"],
        concept_hints=[],
        budget_multiplier=1.0,
    ),
}


# ── IntentRouter ──────────────────────────────────────────────────
class IntentRouter:
    """
    classify(task)  → IntentType
    route(task)     → RouteConfig
    explain(task)   → 可读决策说明
    """

    def __init__(
        self,
        route_table: Optional[Dict[IntentType, RouteConfig]] = None,
    ):
        self.route_table = route_table or _DEFAULT_ROUTE_TABLE

    def classify(
        self,
        task: str,
        extra_keywords: Optional[List[str]] = None,
    ) -> IntentType:
        """
        关键词打分分类（生产环境可无缝替换为 LLM 分类器）。
        每匹配一个关键词得 1 分，取最高分意图；平局取优先级最高的。
        """
        task_lower = task.lower()
        extra = [k.lower() for k in (extra_keywords or [])]
        scores: Dict[IntentType, int] = {intent: 0 for intent in IntentType}

        for intent, kws in _INTENT_KEYWORDS.items():
            for kw in kws:
                kw_l = kw.lower()
                if kw_l in task_lower or kw_l in extra:
                    scores[intent] += 1

        best = max(scores, key=lambda i: scores[i])
        return best if scores[best] > 0 else IntentType.GENERAL

    def route(
        self,
        task: str,
        extra_keywords: Optional[List[str]] = None,
    ) -> RouteConfig:
        """classify + 返回路由配置"""
        intent = self.classify(task, extra_keywords)
        return self.route_table[intent]

    def explain(
        self,
        task: str,
        extra_keywords: Optional[List[str]] = None,
    ) -> str:
        """格式化的路由决策说明（便于调试与日志）"""
        intent = self.classify(task, extra_keywords)
        cfg = self.route_table[intent]
        return (
            f"Task   : {task[:70]}\n"
            f"  Intent : {intent.value}\n"
            f"  Domains: {cfg.domains}\n"
            f"  Tiers  : {cfg.tiers}\n"
            f"  Hints  : {cfg.concept_hints}\n"
            f"  Budget : ×{cfg.budget_multiplier}"
        )
