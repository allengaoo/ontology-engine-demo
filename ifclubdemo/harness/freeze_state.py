"""
freeze_state — workspace 级写冻结前缀（分层稳定点）

落盘：workspace/.ontology_agent/freeze.json
EP PASS 后可追加前缀；AtomicityCheck / DiffApplier 拒绝改动冻结路径。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List


FREEZE_REL = Path(".ontology_agent") / "freeze.json"


def freeze_path(workspace_root: Path) -> Path:
    return Path(workspace_root).resolve() / FREEZE_REL


def load_frozen_prefixes(workspace_root: Path) -> List[str]:
    path = freeze_path(workspace_root)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    prefixes = data.get("prefixes") or []
    out: List[str] = []
    for p in prefixes:
        s = str(p).replace("\\", "/").lstrip("./")
        if s and s not in out:
            out.append(s if s.endswith("/") else s + "/")
    return out


def add_frozen_prefixes(workspace_root: Path, prefixes: Iterable[str]) -> List[str]:
    current = load_frozen_prefixes(workspace_root)
    for p in prefixes:
        s = str(p).replace("\\", "/").lstrip("./")
        if not s:
            continue
        if not s.endswith("/"):
            s = s + "/"
        if s not in current:
            current.append(s)
    path = freeze_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"prefixes": current}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return current


def is_frozen(rel_path: str, frozen_prefixes: Iterable[str]) -> bool:
    rel = (rel_path or "").replace("\\", "/").lstrip("./")
    for pref in frozen_prefixes:
        p = pref.replace("\\", "/").lstrip("./")
        if not p:
            continue
        if not p.endswith("/"):
            p = p + "/"
        if rel.startswith(p) or rel == p.rstrip("/"):
            return True
    return False
