"""
dag_state — EP 执行状态持久化 + --resume（Phase 8 Harness）
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class EPCheckpoint:
    ep_id: str
    phase: str
    struct_retry: int = 0
    impl_retry: int = 0
    completed_units: List[str] = field(default_factory=list)
    plan_id: Optional[str] = None
    task_description: str = ""
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    extra: Dict[str, Any] = field(default_factory=dict)


class DagStateStore:
    """EP 断点续跑存储（JSON 文件）。"""

    def __init__(self, store_dir: Path):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def new_ep_id(self) -> str:
        return f"ep-{uuid.uuid4().hex[:8]}"

    def save(self, checkpoint: EPCheckpoint) -> Path:
        checkpoint.updated_at = datetime.now().isoformat()
        path = self.store_dir / f"{checkpoint.ep_id}.json"
        path.write_text(json.dumps(asdict(checkpoint), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load(self, ep_id: str) -> Optional[EPCheckpoint]:
        path = self.store_dir / f"{ep_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return EPCheckpoint(**data)

    def list_eps(self) -> List[str]:
        return sorted(p.stem for p in self.store_dir.glob("ep-*.json"))
