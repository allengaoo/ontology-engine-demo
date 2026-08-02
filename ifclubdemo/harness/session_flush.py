"""
session_flush — EP 结束时 session 级记忆清理（Phase 8 P1）

对话级/过程级内容：压缩摘要写入会话目录，不进入 Ontology inject（共享记忆）。
共享记忆只走 PromotionGate → MemoryEPWriteback / MemoryWriteback。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from background_task_store import BackgroundTaskStore

from harness.ep_coordinator import EPTurnRecord


class SessionFlush:
    """EP 边界 session 清理 + 会话归档。"""

    def __init__(
        self,
        bg_store: Optional[BackgroundTaskStore] = None,
        *,
        workspace_root: Optional[Path] = None,
    ):
        self.bg_store = bg_store or BackgroundTaskStore()
        self.workspace_root = Path(workspace_root) if workspace_root else None

    def compress_turns(self, turns: List[EPTurnRecord], max_len: int = 400) -> str:
        """将 EP 回合压成一行摘要（审计/日志用，不进共享记忆）。"""
        parts = []
        for t in turns:
            label = t.step_label or t.phase.value
            parts.append(f"{t.agent_name}/{label}:{t.outcome[:40]}")
        text = " | ".join(parts)
        return text[:max_len] + ("..." if len(text) > max_len else "")

    def session_dir(self, session_id: str) -> Optional[Path]:
        if not self.workspace_root or not session_id:
            return None
        d = self.workspace_root / ".ontology_agent" / "sessions" / session_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def archive_ep(
        self,
        *,
        session_id: str,
        ep_id: str,
        ep_label: str,
        task_description: str,
        status: str,
        turns: List[EPTurnRecord],
        promotion_summary: str = "",
        shared_written: Optional[List[str]] = None,
    ) -> Optional[Path]:
        """把本 EP 的会话痕迹追加到 sessions/<id>/archive.jsonl（不进 inject）。"""
        root = self.session_dir(session_id)
        if root is None:
            return None
        archive = root / "archive.jsonl"
        record = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "session_id": session_id,
            "ep_id": ep_id,
            "ep_label": ep_label,
            "status": status,
            "task": task_description[:500],
            "turns_summary": self.compress_turns(turns),
            "turns": [
                {
                    "phase": t.phase.value if hasattr(t.phase, "value") else str(t.phase),
                    "agent": t.agent_name,
                    "label": t.step_label,
                    "outcome": t.outcome,
                    "rule_id": t.rule_id,
                }
                for t in turns
            ],
            "promotion_summary": promotion_summary,
            "shared_written": shared_written or [],
            "memory_kind": "session",  # 显式标注：会话记忆，非共享
        }
        with archive.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        # 同步一份可读 markdown 摘要
        md = root / "SESSION.md"
        with md.open("a", encoding="utf-8") as f:
            f.write(
                f"\n## {ep_label} ({ep_id}) — {status}\n"
                f"- task: {task_description[:200]}\n"
                f"- summary: {record['turns_summary'][:300]}\n"
                f"- shared_written: {shared_written or []}\n"
            )
        return archive

    def flush_ep_session(self, task: Any) -> int:
        """清空 bg_store 中未消费的 EP 内缓冲（会话瞬时记忆）。"""
        n = len(self.bg_store.pending())
        if n:
            self.bg_store.flush()
        if task.context is not None:
            task.context.pop("_bg_results", None)
            task.context.pop("_struct_feedback", None)
            task.context.pop("_force_impl_fail", None)
            task.context.pop("_force_struct_fail", None)
            task.context.pop("_last_verify_feedback", None)
        return n

    @property
    def pending_count(self) -> int:
        return len(self.bg_store.pending())
