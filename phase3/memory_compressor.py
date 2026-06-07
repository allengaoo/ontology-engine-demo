"""
MemoryCompressor — Token 预算分级压缩（Compression 能力）

解决的问题：
  检索到 N 条相关记忆，但 Token 预算有限，需要在保留关键信息的
  前提下，将上下文压缩到预算以内。

Token 预算分级（来自设计文档 §3.1 能力3）：
  CRITICAL   ：固定保留，永远不压缩、不裁剪（600 tokens 基准）
  RULE       ：动态保留，当前任务命中的规则（1800 tokens 基准）
  CONTEXT    ：滑动窗口，最近 N 步对话状态（800 tokens 基准）
  BACKGROUND ：按需填充，Token 充足时才加入（600 tokens 基准）
  预留缓冲   ：200 tokens

压缩策略：
  - CRITICAL 使用 compressed 字段（已预压缩），不再二次压缩
  - RULE/CONTEXT 超出预算时截断最低优先级条目
  - BACKGROUND 整体可选，Token 不足时直接跳过

Token 计数：粗估，1 token ≈ 1.5 个汉字 或 4 个英文字符
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .memory_retriever import RetrievalResult
from .memory_store import Memory


def estimate_tokens(text: str) -> int:
    """粗估 token 数量（无需 tiktoken 依赖）"""
    # 中文字符：约 1.5 字/token；英文单词：约 1 词/token
    chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4) + 1


@dataclass
class TokenBudget:
    """Token 预算配置"""
    critical:   int = 600    # CRITICAL 约束（固定保留）
    rule:       int = 1800   # 直接相关规则（动态）
    context:    int = 800    # 历史上下文（滑动窗口）
    background: int = 600    # 背景知识（按需填充）
    buffer:     int = 200    # 预留缓冲

    @property
    def total(self) -> int:
        return self.critical + self.rule + self.context + self.background + self.buffer


@dataclass
class CompressedContext:
    """压缩后的上下文，含分层内容和 token 统计"""
    critical_text:   str
    rule_text:       str
    context_text:    str
    background_text: str

    critical_tokens:   int
    rule_tokens:       int
    context_tokens:    int
    background_tokens: int

    memories_used: int
    memories_dropped: int

    @property
    def total_tokens(self) -> int:
        return (self.critical_tokens + self.rule_tokens +
                self.context_tokens + self.background_tokens)

    def to_prompt_text(self) -> str:
        """生成可注入 LLM 的上下文文本"""
        parts = []
        if self.critical_text:
            parts.append(f"【硬约束（必须遵守）】\n{self.critical_text}")
        if self.rule_text:
            parts.append(f"【相关规则】\n{self.rule_text}")
        if self.context_text:
            parts.append(f"【当前会话上下文】\n{self.context_text}")
        if self.background_text:
            parts.append(f"【背景知识】\n{self.background_text}")
        return "\n\n".join(parts)

    def stats(self) -> str:
        return (
            f"tokens: CRITICAL={self.critical_tokens} "
            f"RULE={self.rule_tokens} "
            f"CONTEXT={self.context_tokens} "
            f"BACKGROUND={self.background_tokens} "
            f"total={self.total_tokens} | "
            f"used={self.memories_used} dropped={self.memories_dropped}"
        )


class MemoryCompressor:
    """按 Token 预算将检索结果压缩成可注入的上下文"""

    def __init__(self, budget: Optional[TokenBudget] = None):
        self.budget = budget or TokenBudget()

    def compress(self, retrieval: RetrievalResult) -> CompressedContext:
        """
        核心压缩逻辑：
        1. CRITICAL 全量使用 compressed 字段（固定，永远保留）
        2. RULE 按预算逐条加入，超出则截断
        3. CONTEXT 同上（预算更小）
        4. BACKGROUND Token 充足时才加入，否则跳过
        """
        used = 0
        dropped = 0

        # ── CRITICAL：全量 compressed，固定保留 ──────────────────────────
        critical_lines = [m.compressed for m in retrieval.critical]
        critical_text = "\n".join(critical_lines)
        critical_tokens = estimate_tokens(critical_text)

        # ── RULE：逐条按预算加入 ──────────────────────────────────────────
        rule_lines: List[str] = []
        rule_tokens = 0
        for m in retrieval.rule:
            text = m.compressed if len(m.compressed) < len(m.content) * 0.7 else m.content
            t = estimate_tokens(text)
            if rule_tokens + t <= self.budget.rule:
                rule_lines.append(text)
                rule_tokens += t
                used += 1
            else:
                dropped += 1
        rule_text = "\n".join(rule_lines)

        # ── CONTEXT：逐条按预算加入 ──────────────────────────────────────
        context_lines: List[str] = []
        context_tokens = 0
        for m in retrieval.context:
            text = m.compressed if len(m.compressed) < len(m.content) * 0.7 else m.content
            t = estimate_tokens(text)
            if context_tokens + t <= self.budget.context:
                context_lines.append(text)
                context_tokens += t
                used += 1
            else:
                dropped += 1
        context_text = "\n".join(context_lines)

        # ── BACKGROUND：Token 充足才加入，否则整体跳过 ──────────────────
        remaining = (self.budget.total - self.budget.buffer
                     - critical_tokens - rule_tokens - context_tokens)
        background_lines: List[str] = []
        background_tokens = 0
        if remaining > 100:
            for m in retrieval.background:
                text = m.compressed
                t = estimate_tokens(text)
                if background_tokens + t <= min(remaining, self.budget.background):
                    background_lines.append(text)
                    background_tokens += t
                    used += 1
                else:
                    dropped += 1
        else:
            dropped += len(retrieval.background)
        background_text = "\n".join(background_lines)

        return CompressedContext(
            critical_text=critical_text,
            rule_text=rule_text,
            context_text=context_text,
            background_text=background_text,
            critical_tokens=critical_tokens,
            rule_tokens=rule_tokens,
            context_tokens=context_tokens,
            background_tokens=background_tokens,
            memories_used=used,
            memories_dropped=dropped,
        )

    def compress_raw_text(self, text: str, max_tokens: int) -> str:
        """简单文本截断压缩（用于历史对话摘要）"""
        if estimate_tokens(text) <= max_tokens:
            return text
        # 按字符截断
        target_chars = max_tokens * 3
        return text[:target_chars] + "…（已截断）"
