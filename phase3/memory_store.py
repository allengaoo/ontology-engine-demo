"""
MemoryStore — 记忆的存储与生命周期管理

对应记忆系统两个能力：
  Classification（分类）：写入时确定 layer，决定检索时能否找到
  Eviction（淘汰）：状态机管理记忆生命周期，防止过期记忆污染

设计说明：
  Phase 1-2 用 JSONL，满足"追加写 + 顺序扫"的需求。
  记忆系统需要按 layer/status/tag 跨字段查询，JSONL 撑不住，
  这是第一次在本系列中正式引入 SQLite。

记忆分层（简化自设计文档 L3/L4/CC）：
  CRITICAL   — 永远保留的硬约束（如"认证有效期必须>=30天"）
  RULE       — 当前任务直接相关的规则/约束
  CONTEXT    — 近期对话的工作状态（滑动窗口保留）
  BACKGROUND — 背景知识（Token 充足时才注入）

记忆状态机：
  hot → warm → cold → archived
              ↓
          deprecated（关联规则变更时）

双层记忆模型（参考 AgentScope 分层记忆设计）：
  第一层·流水账（DailyLogWriter）
    - 原始事实，只追加，不去重
    - 写入路径：memory/daily/YYYY-MM-DD.jsonl
    - 每次 write() 调用后同步追加，不影响 SQLite 主存储

  第二层·策划后记忆（MemoryStore SQLite）
    - 经过 layer/tags/confidence 标注的结构化条目
    - LLM 二次加工后的版本（由调用方写入）
    - 检索、压缩、淘汰都针对此层
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class MemoryLayer(str, Enum):
    CRITICAL   = "critical"    # 永远保留的硬约束
    RULE       = "rule"        # 当前任务相关规则
    CONTEXT    = "context"     # 近期对话工作状态
    BACKGROUND = "background"  # 背景知识


class MemoryStatus(str, Enum):
    HOT        = "hot"         # 活跃，频繁命中
    WARM       = "warm"        # 温冷，近期未命中
    COLD       = "cold"        # 冷存，候选清理
    DEPRECATED = "deprecated"  # 关联规则已变更，不再可信
    ARCHIVED   = "archived"    # 已归档删除


@dataclass
class Memory:
    id: str
    content: str               # 记忆原文
    compressed: str            # 压缩后的精要版本
    layer: MemoryLayer
    status: MemoryStatus
    tags: List[str]            # 关键词标签，用于检索匹配
    hit_count: int = 0
    confidence: float = 1.0    # 可信度分（失败操作会降低此分）
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_accessed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    source_session: Optional[str] = None  # 来源会话 ID

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "compressed": self.compressed,
            "layer": self.layer.value,
            "status": self.status.value,
            "tags": json.dumps(self.tags, ensure_ascii=False),
            "hit_count": self.hit_count,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "last_accessed_at": self.last_accessed_at,
            "source_session": self.source_session,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Memory":
        return cls(
            id=row["id"],
            content=row["content"],
            compressed=row["compressed"],
            layer=MemoryLayer(row["layer"]),
            status=MemoryStatus(row["status"]),
            tags=json.loads(row["tags"]),
            hit_count=row["hit_count"],
            confidence=row["confidence"],
            created_at=row["created_at"],
            last_accessed_at=row["last_accessed_at"],
            source_session=row["source_session"],
        )


class MemoryStore:
    """记忆的持久化存储与生命周期管理（SQLite）"""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS memories (
        id               TEXT PRIMARY KEY,
        content          TEXT NOT NULL,
        compressed       TEXT NOT NULL,
        layer            TEXT NOT NULL,
        status           TEXT NOT NULL DEFAULT 'hot',
        tags             TEXT NOT NULL DEFAULT '[]',
        hit_count        INTEGER NOT NULL DEFAULT 0,
        confidence       REAL NOT NULL DEFAULT 1.0,
        created_at       TEXT NOT NULL,
        last_accessed_at TEXT NOT NULL,
        source_session   TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_memories_layer  ON memories(layer);
    CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
    """

    def __init__(self, db_path: Path, daily_log_dir: Optional[Path] = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self._SCHEMA)
        self._conn.commit()
        # 流水账写入器：若未指定目录，与 db 文件同目录
        log_dir = daily_log_dir or self.db_path.parent
        self.daily_log = DailyLogWriter(log_dir)
        self._seed_critical_memories()

    # ── 写入 ─────────────────────────────────────────────────────────────

    def write(
        self,
        content: str,
        compressed: str,
        layer: MemoryLayer,
        tags: List[str],
        source_session: Optional[str] = None,
        confidence: float = 1.0,
    ) -> Memory:
        """写入一条记忆（Classification：调用方负责指定 layer 和 tags）

        tags 来源规范（确保检索时能精准命中）：
          CRITICAL 层: Schema 字段名 + 参数名（初始化时一次性写入）
          RULE 层:     操作 ID + 规则 ID（来自操作执行结果）
          CONTEXT 层:  操作 ID + 触发规则 ID（来自被拒绝的操作）

        同时向流水账（DailyLogWriter）追加原始记录，供审计和回溯。
        流水账写失败不影响主流程。
        """
        memory = Memory(
            id=f"mem-{uuid.uuid4().hex[:8]}",
            content=content,
            compressed=compressed,
            layer=layer,
            status=MemoryStatus.HOT,
            tags=tags,
            confidence=confidence,
            source_session=source_session,
        )
        self._conn.execute(
            """INSERT INTO memories VALUES
               (:id,:content,:compressed,:layer,:status,:tags,
                :hit_count,:confidence,:created_at,:last_accessed_at,:source_session)""",
            memory.to_dict(),
        )
        self._conn.commit()
        # 同步追加到流水账（第一层·原始记录）
        self.daily_log.append(
            content=content,
            layer=layer.value,
            tags=tags,
            session=source_session,
        )
        return memory

    def write_critical(self, content: str, compressed: str, tags: List[str]) -> Memory:
        """写入 CRITICAL 层记忆（硬约束，永远保留）"""
        return self.write(content, compressed, MemoryLayer.CRITICAL, tags, confidence=1.0)

    # ── 查询 ─────────────────────────────────────────────────────────────

    def get_by_layer(
        self,
        layer: MemoryLayer,
        exclude_status: Optional[List[MemoryStatus]] = None,
    ) -> List[Memory]:
        """按层获取记忆（排除 deprecated/archived）"""
        exclude = exclude_status or [MemoryStatus.DEPRECATED, MemoryStatus.ARCHIVED]
        placeholders = ",".join("?" * len(exclude))
        rows = self._conn.execute(
            f"SELECT * FROM memories WHERE layer=? AND status NOT IN ({placeholders})"
            " ORDER BY hit_count DESC, confidence DESC",
            [layer.value] + [s.value for s in exclude],
        ).fetchall()
        return [Memory.from_row(r) for r in rows]

    def get_all_active(self) -> List[Memory]:
        """获取所有活跃记忆（非 deprecated/archived）"""
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE status NOT IN ('deprecated','archived')"
            " ORDER BY layer, hit_count DESC"
        ).fetchall()
        return [Memory.from_row(r) for r in rows]

    def search_by_tags(self, keywords: List[str], limit: int = 20) -> List[Memory]:
        """按关键词搜索记忆（简单字符串匹配）"""
        results: List[Memory] = []
        seen: set = set()
        for kw in keywords:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE status NOT IN ('deprecated','archived')"
                " AND (tags LIKE ? OR content LIKE ? OR compressed LIKE ?)"
                " ORDER BY hit_count DESC LIMIT ?",
                [f"%{kw}%", f"%{kw}%", f"%{kw}%", limit],
            ).fetchall()
            for row in rows:
                m = Memory.from_row(row)
                if m.id not in seen:
                    seen.add(m.id)
                    results.append(m)
        return results

    def record_hit(self, memory_id: str) -> None:
        """记录一次命中，更新访问时间和命中计数"""
        self._conn.execute(
            "UPDATE memories SET hit_count=hit_count+1, last_accessed_at=? WHERE id=?",
            [datetime.now().isoformat(), memory_id],
        )
        self._conn.commit()

    # ── 淘汰（Eviction）——生命周期管理 ────────────────────────────────────

    def deprecate(self, memory_id: str, reason: str = "") -> None:
        """将记忆标记为 deprecated（关联规则变更时调用）"""
        self._conn.execute(
            "UPDATE memories SET status='deprecated' WHERE id=?",
            [memory_id],
        )
        self._conn.commit()

    def lower_confidence(self, memory_id: str, delta: float = 0.2) -> None:
        """降低记忆可信度（基于此记忆的操作失败时调用）"""
        self._conn.execute(
            "UPDATE memories SET confidence=MAX(0.0, confidence-?) WHERE id=?",
            [delta, memory_id],
        )
        self._conn.commit()

    def run_eviction(self, cold_days: int = 30, cold_hits: int = 2) -> Dict[str, int]:
        """
        执行淘汰周期：
        - hit_count < cold_hits 且距上次访问 > cold_days 天 → 降级为 cold
        - status=cold 且距上次访问 > cold_days*3 天 → 降级为 archived
        - confidence < 0.3 → 标记为 deprecated
        """
        now = datetime.now()
        cutoff_warm = (now - timedelta(days=cold_days)).isoformat()
        cutoff_archive = (now - timedelta(days=cold_days * 3)).isoformat()

        r1 = self._conn.execute(
            "UPDATE memories SET status='warm' WHERE status='hot'"
            " AND hit_count<? AND last_accessed_at<?",
            [cold_hits, cutoff_warm],
        ).rowcount
        r2 = self._conn.execute(
            "UPDATE memories SET status='cold' WHERE status='warm'"
            " AND last_accessed_at<?",
            [cutoff_archive],
        ).rowcount
        r3 = self._conn.execute(
            "UPDATE memories SET status='deprecated' WHERE confidence<0.3"
            " AND layer != 'critical'",
        ).rowcount
        self._conn.commit()
        return {"to_warm": r1, "to_cold": r2, "to_deprecated": r3}

    def stats(self) -> Dict[str, Any]:
        """返回当前记忆库统计"""
        rows = self._conn.execute(
            "SELECT layer, status, COUNT(*) as cnt FROM memories GROUP BY layer, status"
        ).fetchall()
        result: Dict[str, Any] = {}
        for row in rows:
            key = f"{row['layer']}/{row['status']}"
            result[key] = row["cnt"]
        return result

    # ── 种子数据：从 Phase 1 Schema 提取 CRITICAL 约束 ───────────────────

    def _seed_critical_memories(self) -> None:
        """预置来自本体 Schema 的 CRITICAL 约束记忆（幂等：已存在则跳过）"""
        existing = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM memories WHERE layer='critical'"
        ).fetchone()["cnt"]
        if existing > 0:
            return

        critical_seeds = [
            {
                "content": "供应商认证证书剩余有效期必须大于等于 30 天，才能发起采购订单。违反此约束，本体引擎将强制回滚操作并拒绝执行。",
                "compressed": "[CRITICAL] 认证剩余天数 >= 30 天，否则引擎回滚",
                "tags": ["认证", "certification", "有效期", "30天", "采购"],
            },
            {
                "content": "供应商的状态必须为 active，合同状态必须为 valid，才允许发起采购操作。",
                "compressed": "[CRITICAL] 供应商状态=active 且合同状态=valid",
                "tags": ["供应商", "状态", "合同", "active", "valid"],
            },
            {
                "content": "采购操作后，供应商的未结金额不得超过其信用额度上限（credit_limit）。超出则触发 credit_limit_check 规则，订单回滚。",
                "compressed": "[CRITICAL] 未结金额 <= 信用额度，否则引擎回滚",
                "tags": ["信用额度", "credit_limit", "未结金额", "采购"],
            },
            {
                "content": "单笔采购金额不得超过 50 万元。超过需走财务总监特殊审批流程。",
                "compressed": "[CRITICAL] 单笔采购 <= 50万，超额需财务总监审批",
                "tags": ["金额", "50万", "审批", "大额订单"],
            },
        ]

        for seed in critical_seeds:
            self.write_critical(
                content=seed["content"],
                compressed=seed["compressed"],
                tags=seed["tags"],
            )


# ── 第一层·流水账 ──────────────────────────────────────────────────────────────

class DailyLogWriter:
    """
    每日流水账写入器（对应 AgentScope 的 memory/YYYY-MM-DD.md 机制）

    设计原则：
      - 只追加，不去重，不修改
      - 与 SQLite 主存储（MemoryStore）完全独立——两层互不干扰
      - 流水账记录"原始事实"；MemoryStore 记录"经分类标注的结构化记忆"
      - 第二层（MemoryStore）是检索和压缩的目标；
        第一层是审计、回溯的原始存档

    文件路径：<base_dir>/daily/YYYY-MM-DD.jsonl
    每行一条 JSON，格式：
      {"ts": ISO8601, "session": str, "layer": str, "content": str, "tags": [...]}
    """

    def __init__(self, base_dir: Path):
        self.log_dir = Path(base_dir) / "daily"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def append(
        self,
        content: str,
        layer: str,
        tags: List[str],
        session: Optional[str] = None,
    ) -> None:
        """追加一条原始事实记录（fire-and-forget，不抛异常）"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            log_path = self.log_dir / f"{today}.jsonl"
            entry = {
                "ts": datetime.now().isoformat(),
                "session": session or "",
                "layer": layer,
                "content": content,
                "tags": tags,
            }
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 流水账写失败不中断主流程

    def read_today(self) -> List[Dict[str, Any]]:
        """读取今日流水账（供调试/审计）"""
        today = datetime.now().strftime("%Y-%m-%d")
        log_path = self.log_dir / f"{today}.jsonl"
        if not log_path.exists():
            return []
        entries = []
        with log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return entries

    def count_today(self) -> int:
        """返回今日流水账条数"""
        return len(self.read_today())
