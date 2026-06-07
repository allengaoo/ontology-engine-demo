"""
SessionManager — 会话管理与历史压缩

职责：
- 维护多轮对话的 turn 历史
- 当历史 token 超过阈值时，自动触发压缩（生成摘要替代全量历史）
- 跨会话持久化：会话状态存入 SQLite

多轮对话 token 增长的关键数字（来自设计文档 §二）：
  第  1 轮：约  500 tokens
  第 10 轮：约 8,000 tokens（接近推理边界）
  第 20 轮：约 20,000 tokens（超窗口）

SessionManager 的目标：把第 10 轮的历史 token 控制在 800 以内。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .memory_compressor import estimate_tokens, MemoryCompressor
from .memory_store import Memory, MemoryLayer, MemoryStore


@dataclass
class Turn:
    """一轮对话"""
    turn_id:    int
    role:       str   # user / assistant
    content:    str
    tokens:     int
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SessionState:
    """当前会话的工作状态（被压缩摘要使用）"""
    session_id:      str
    task:            str
    confirmed_items: List[str]   # 已确认的修改/决定
    pending_items:   List[str]   # 待确认的议题
    turn_count:      int = 0
    compressed_summary: str = ""  # 历史压缩摘要（替代原始 turns）


class SessionManager:
    """多轮对话的会话管理与历史压缩"""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS sessions (
        session_id   TEXT PRIMARY KEY,
        task         TEXT NOT NULL,
        state_json   TEXT NOT NULL DEFAULT '{}',
        created_at   TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS session_turns (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id   TEXT NOT NULL,
        turn_id      INTEGER NOT NULL,
        role         TEXT NOT NULL,
        content      TEXT NOT NULL,
        tokens       INTEGER NOT NULL,
        created_at   TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_turns_session ON session_turns(session_id, turn_id);
    """

    # 当历史 token 超过此阈值时触发压缩
    COMPRESS_THRESHOLD = 1500

    def __init__(self, db_path: Path, memory_store: MemoryStore):
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self._SCHEMA)
        self._conn.commit()
        self.memory_store = memory_store
        self.compressor = MemoryCompressor()

    # ── 会话管理 ─────────────────────────────────────────────────────────

    def create_session(self, task: str) -> str:
        """创建新会话，返回 session_id"""
        session_id = f"sess-{uuid.uuid4().hex[:8]}"
        state = SessionState(
            session_id=session_id,
            task=task,
            confirmed_items=[],
            pending_items=[],
        )
        self._conn.execute(
            "INSERT INTO sessions VALUES (?,?,?,?)",
            [session_id, task, json.dumps(self._state_to_dict(state)), datetime.now().isoformat()],
        )
        self._conn.commit()
        return session_id

    def add_turn(self, session_id: str, role: str, content: str) -> Turn:
        """追加一轮对话，超过阈值时自动触发压缩"""
        tokens = estimate_tokens(content)
        turn_id = self._next_turn_id(session_id)
        self._conn.execute(
            "INSERT INTO session_turns (session_id,turn_id,role,content,tokens,created_at)"
            " VALUES (?,?,?,?,?,?)",
            [session_id, turn_id, role, content, tokens, datetime.now().isoformat()],
        )
        self._conn.commit()

        turn = Turn(turn_id=turn_id, role=role, content=content, tokens=tokens)

        # 检查是否需要压缩
        total_tokens = self._total_history_tokens(session_id)
        if total_tokens > self.COMPRESS_THRESHOLD:
            self._compress_history(session_id)

        return turn

    def get_history(self, session_id: str, max_turns: int = 10) -> List[Turn]:
        """获取最近 N 轮对话（压缩后的历史只剩 summary 轮）"""
        rows = self._conn.execute(
            "SELECT * FROM session_turns WHERE session_id=?"
            " ORDER BY turn_id DESC LIMIT ?",
            [session_id, max_turns],
        ).fetchall()
        turns = [Turn(
            turn_id=r["turn_id"],
            role=r["role"],
            content=r["content"],
            tokens=r["tokens"],
            created_at=r["created_at"],
        ) for r in reversed(rows)]
        return turns

    def get_state(self, session_id: str) -> Optional[SessionState]:
        """获取会话工作状态"""
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id=?", [session_id]
        ).fetchone()
        if not row:
            return None
        state_dict = json.loads(row["state_json"])
        return SessionState(
            session_id=session_id,
            task=row["task"],
            confirmed_items=state_dict.get("confirmed_items", []),
            pending_items=state_dict.get("pending_items", []),
            turn_count=state_dict.get("turn_count", 0),
            compressed_summary=state_dict.get("compressed_summary", ""),
        )

    def update_state(
        self,
        session_id: str,
        confirmed: Optional[List[str]] = None,
        pending: Optional[List[str]] = None,
    ) -> None:
        """更新会话工作状态（记录已确认/待确认的议题）"""
        state = self.get_state(session_id)
        if not state:
            return
        if confirmed:
            state.confirmed_items.extend(confirmed)
        if pending:
            state.pending_items = pending
        state.turn_count += 1
        self._save_state(state)

    def build_history_context(self, session_id: str) -> str:
        """
        构建注入 LLM 的历史上下文：
        - 若有压缩摘要，优先使用摘要
        - 再追加最近几轮原始对话
        """
        state = self.get_state(session_id)
        if not state:
            return ""

        parts: List[str] = []

        if state.compressed_summary:
            parts.append(f"[历史摘要] {state.compressed_summary}")

        if state.confirmed_items:
            items_str = "；".join(state.confirmed_items)
            parts.append(f"[已确认事项] {items_str}")

        recent_turns = self.get_history(session_id, max_turns=4)
        if recent_turns:
            dialog = "\n".join(
                f"{t.role}: {t.content[:200]}" for t in recent_turns
            )
            parts.append(f"[近期对话]\n{dialog}")

        return "\n\n".join(parts)

    def history_token_count(self, session_id: str) -> int:
        """返回当前历史 token 数（用于展示 token 增长曲线）"""
        return self._total_history_tokens(session_id)

    # ── 内部方法 ─────────────────────────────────────────────────────────

    def _compress_history(self, session_id: str) -> None:
        """
        历史压缩：将超阈值的历史 turns 合并为摘要，
        只保留最近 3 轮原始对话，其余替换为摘要。
        同时将已确认约束写入记忆系统的 CONTEXT 层。
        """
        turns = self.get_history(session_id, max_turns=50)
        if len(turns) <= 4:
            return

        # 旧 turns 生成摘要（简单拼接，实际可调用 LLM 生成摘要）
        old_turns = turns[:-3]
        summary_parts = []
        for t in old_turns:
            summary_parts.append(f"{t.role}: {t.content[:100]}")
        raw_summary = " | ".join(summary_parts)
        compressed_summary = self.compressor.compress_raw_text(raw_summary, max_tokens=300)

        # 更新 state
        state = self.get_state(session_id)
        if state:
            state.compressed_summary = compressed_summary
            self._save_state(state)

        # 删除旧 turns，只保留最近 3 轮
        keep_ids = [t.turn_id for t in turns[-3:]]
        placeholders = ",".join("?" * len(keep_ids))
        self._conn.execute(
            f"DELETE FROM session_turns WHERE session_id=? AND turn_id NOT IN ({placeholders})",
            [session_id] + keep_ids,
        )
        self._conn.commit()

        # 将本次确认的约束写入 CONTEXT 层记忆
        if state and state.confirmed_items:
            for item in state.confirmed_items:
                self.memory_store.write(
                    content=item,
                    compressed=f"[本次确认] {item[:80]}",
                    layer=MemoryLayer.CONTEXT,
                    tags=item.split()[:5],
                    source_session=session_id,
                )

    def _total_history_tokens(self, session_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(tokens),0) as total FROM session_turns WHERE session_id=?",
            [session_id],
        ).fetchone()
        return row["total"] if row else 0

    def _next_turn_id(self, session_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(turn_id),0)+1 as next_id FROM session_turns WHERE session_id=?",
            [session_id],
        ).fetchone()
        return row["next_id"] if row else 1

    def _save_state(self, state: SessionState) -> None:
        self._conn.execute(
            "UPDATE sessions SET state_json=? WHERE session_id=?",
            [json.dumps(self._state_to_dict(state)), state.session_id],
        )
        self._conn.commit()

    @staticmethod
    def _state_to_dict(state: SessionState) -> Dict[str, Any]:
        return {
            "confirmed_items": state.confirmed_items,
            "pending_items": state.pending_items,
            "turn_count": state.turn_count,
            "compressed_summary": state.compressed_summary,
        }
