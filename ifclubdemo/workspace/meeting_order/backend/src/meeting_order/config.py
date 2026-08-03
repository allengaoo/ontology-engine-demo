from pathlib import Path
import os
ROOT = Path(__file__).resolve().parents[3]
DB_BACKEND = os.environ.get("MEETING_DB_BACKEND", "sqlite")
DB_PATH = Path(os.environ.get("MEETING_DB", str(ROOT / "data" / "meeting_order.db")))
MYSQL_DSN = os.environ.get("MEETING_MYSQL_DSN", "")

# API URL 规范化：全局前缀只定义一次；router 只写资源段；main 用此常量挂载
API_V1_PREFIX = "/api/v1"
