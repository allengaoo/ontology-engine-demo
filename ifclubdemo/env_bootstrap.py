"""加载 ifclubdemo/.env，并解析 WORKSPACE 默认路径。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

IFCLUB_ROOT = Path(__file__).resolve().parent
_ENV_LOADED = False


def load_env(*, override: bool = False) -> Path:
    """优先加载 ifclubdemo/.env，其次上级 democode/.env。返回实际加载路径（可能不存在）。"""
    global _ENV_LOADED
    candidates = [IFCLUB_ROOT / ".env", IFCLUB_ROOT.parent / ".env"]
    chosen: Optional[Path] = next((c for c in candidates if c.exists()), None)
    if _ENV_LOADED:
        return chosen or IFCLUB_ROOT / ".env"

    _ENV_LOADED = True
    if chosen is None:
        return IFCLUB_ROOT / ".env"

    try:
        from dotenv import load_dotenv

        load_dotenv(chosen, override=override)
    except ImportError:
        with open(chosen, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if not key:
                    continue
                if override or key not in os.environ:
                    os.environ[key] = value
    return chosen


def workspace_root() -> Path:
    """IFCLUB_WORKSPACE → 绝对路径，默认 ./workspace。"""
    load_env()
    raw = os.environ.get("IFCLUB_WORKSPACE", "./workspace").strip() or "./workspace"
    p = Path(raw)
    if not p.is_absolute():
        p = (IFCLUB_ROOT / p).resolve()
    return p


def default_app_name() -> str:
    load_env()
    return os.environ.get("IFCLUB_APP", "meeting_order").strip() or "meeting_order"


def default_app_workspace(app: Optional[str] = None) -> Path:
    """$IFCLUB_WORKSPACE/<app>，默认 meeting_order。"""
    name = app or default_app_name()
    return workspace_root() / name
