"""
session_flush — EP 结束时 session 级记忆清理（Phase 8 P1）

对话级/过程级内容：压缩摘要仅用于日志，不进入 Ontology inject。
"""

from __future__ import annotations

from typing import Any, List, Optional

from background_task_store import BackgroundTaskStore

from harness.ep_coordinator import EPTurnRecord


class SessionFlush:
    """EP 边界 session 清理。"""

    def __init__(self, bg_store: Optional[BackgroundTaskStore] = None):
        self.bg_store = bg_store or BackgroundTaskStore()

    def compress_turns(self, turns: List[EPTurnRecord], max_len: int = 400) -> str:
        """将 EP 回合压成一行摘要（审计/日志用，不进共享记忆）。"""
        parts = []
        for t in turns:
            label = t.step_label or t.phase.value
            parts.append(f"{t.agent_name}/{label}:{t.outcome[:40]}")
        text = " | ".join(parts)
        return text[:max_len] + ("..." if len(text) > max_len else "")

    def flush_ep_session(self, task: Any) -> int:
        """清空 bg_store 中未消费的 EP 内缓冲。"""
        n = len(self.bg_store.pending())
        if n:
            self.bg_store.flush()
        if task.context is not None:
            task.context.pop("_bg_results", None)
            task.context.pop("_struct_feedback", None)
            task.context.pop("_force_impl_fail", None)
            task.context.pop("_force_struct_fail", None)
        return n

    @property
    def pending_count(self) -> int:
        return len(self.bg_store.pending())
