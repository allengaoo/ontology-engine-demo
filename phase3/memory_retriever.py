"""
MemoryRetriever — 按需精准提取记忆（Retrieval 能力）

解决的问题：
  用户说"讨论认证规则是否需要调整"，系统需要精准找到相关记忆，
  而不是把全部记忆都塞进上下文。

检索流程（来自设计文档 §3.1 能力2）：
  输入：用户意图（自然语言）
    ↓
  [关键词提取] → 从意图中识别关键实体/操作/约束
    ↓
  [层级定位]   → 判断当前意图属于哪一层（CRITICAL/RULE/CONTEXT）
    ↓
  [图匹配]     → 在对应层做关键词 + tags 匹配
    ↓
  [相关性排序] → 按命中频率和语义距离排序
    ↓
  输出：精准上下文（而非全量记忆）

注：本实现使用关键词匹配，不依赖向量数据库。
    对本体场景（结构化标签 + 有限词汇量）已足够精准。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .memory_store import Memory, MemoryLayer, MemoryStore


# 意图关键词 → 记忆层映射规则
# 用于判断当前意图主要涉及哪一层的记忆
_LAYER_KEYWORDS: Dict[MemoryLayer, List[str]] = {
    MemoryLayer.CRITICAL: [
        "必须", "不得", "强制", "约束", "红线", "硬规则",
        "critical", "必填", "必要",
    ],
    MemoryLayer.RULE: [
        "规则", "认证", "信用", "金额", "审批", "有效期",
        "certification", "credit", "rule", "阈值", "限制",
    ],
    MemoryLayer.CONTEXT: [
        "上次", "之前", "已经", "讨论过", "我们说", "刚才",
        "确认", "决定", "session", "本次",
    ],
}

# 实体关键词映射，用于从意图中快速定位相关标签
_ENTITY_KEYWORDS: Dict[str, List[str]] = {
    "供应商":  ["供应商", "vendor", "supplier", "S-ACME", "S-BETA", "S-GAMMA"],
    "认证":    ["认证", "certification", "ISO", "证书", "有效期"],
    "采购":    ["采购", "订单", "purchase", "order", "金额"],
    "信用":    ["信用", "credit", "额度", "未结金额"],
    "规则":    ["规则", "rule", "约束", "条件", "检查"],
}


class MemoryRetriever:
    """按需精准提取记忆"""

    def __init__(self, store: MemoryStore, default_limit: int = 15):
        self.store = store
        self.default_limit = default_limit

    def retrieve(
        self,
        intent: str,
        extra_keywords: Optional[List[str]] = None,
        limit: int = 0,
    ) -> "RetrievalResult":
        """
        主检索入口：从意图提取关键词，分层检索并排序

        Returns RetrievalResult，包含分层结果和 token 估算
        """
        limit = limit or self.default_limit
        keywords = self._extract_keywords(intent, extra_keywords)

        # CRITICAL 层全量注入（永远保留，不走关键词过滤）
        critical = self.store.get_by_layer(MemoryLayer.CRITICAL)

        # RULE 层按关键词检索
        rule_memories = self._search_layer(keywords, MemoryLayer.RULE, limit)

        # CONTEXT 层按关键词检索（近期对话状态）
        context_memories = self._search_layer(keywords, MemoryLayer.CONTEXT, limit // 2)

        # BACKGROUND 层按关键词检索（背景知识）
        background_memories = self._search_layer(keywords, MemoryLayer.BACKGROUND, limit // 3)

        # 记录命中
        all_hits = rule_memories + context_memories + background_memories
        for m in all_hits:
            self.store.record_hit(m.id)

        return RetrievalResult(
            keywords=keywords,
            critical=critical,
            rule=rule_memories,
            context=context_memories,
            background=background_memories,
        )

    def _extract_keywords(
        self, intent: str, extra: Optional[List[str]] = None
    ) -> List[str]:
        """从意图字符串中提取检索关键词"""
        keywords: List[str] = list(extra or [])

        # 实体关键词匹配
        for entity, kw_list in _ENTITY_KEYWORDS.items():
            for kw in kw_list:
                if kw in intent:
                    keywords.extend(kw_list)
                    keywords.append(entity)
                    break

        # 直接把意图按常见分隔符切分（简单有效）
        for token in intent.replace("，", " ").replace("。", " ").replace("？", " ").split():
            if len(token) >= 2:
                keywords.append(token)

        # 去重，保留顺序
        seen: set = set()
        result: List[str] = []
        for k in keywords:
            if k not in seen:
                seen.add(k)
                result.append(k)
        return result[:20]  # 最多 20 个关键词

    def _search_layer(
        self, keywords: List[str], layer: MemoryLayer, limit: int
    ) -> List[Memory]:
        """在指定层按关键词搜索，按命中分排序"""
        if limit <= 0:
            return []

        candidates = self.store.search_by_tags(keywords, limit=limit * 3)
        layer_candidates = [m for m in candidates if m.layer == layer]

        # 按 hit_count * confidence 排序
        layer_candidates.sort(
            key=lambda m: m.hit_count * m.confidence, reverse=True
        )
        return layer_candidates[:limit]


class RetrievalResult:
    """检索结果：分层存储，供 MemoryCompressor 按预算填充"""

    def __init__(
        self,
        keywords: List[str],
        critical: List[Memory],
        rule: List[Memory],
        context: List[Memory],
        background: List[Memory],
    ):
        self.keywords = keywords
        self.critical = critical
        self.rule = rule
        self.context = context
        self.background = background

    @property
    def all_memories(self) -> List[Memory]:
        return self.critical + self.rule + self.context + self.background

    def summary(self) -> str:
        return (
            f"检索结果：CRITICAL={len(self.critical)} "
            f"RULE={len(self.rule)} "
            f"CONTEXT={len(self.context)} "
            f"BACKGROUND={len(self.background)}"
        )
