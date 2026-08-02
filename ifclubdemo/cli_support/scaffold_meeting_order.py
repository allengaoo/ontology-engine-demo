"""Deterministic meeting_order app scaffold (FastAPI + React)."""

from __future__ import annotations

from pathlib import Path

from workspace_config import WorkspaceConfig


BUSINESS_BRIEF = """# 会议室预订系统 - 业务说明

## 1. 目标

为办公室提供简易会议室预订能力：查看会议室名单，提交预订；合法预订留下，撞车或违规明确拒绝并说明原因。

## 2. 核心对象

- Room：id（可为 None 表示自增）、name、capacity（≥1，仅展示不卡预订）、is_active；禁止 team / slot / active
- Booking：id、room_id、title、booker、start_at、end_at（本地可读时间字符串）；禁止 begin_time / finish_time / slot / team

## 3. 对象关系

- Booking 通过 room_id 关联 Room（N:1 占用）
- 规矩检查落在 domain（纯函数），持久化经 repositories

## 4. 业务动作

- list_rooms / seed_rooms（初始化会议室名单）
- create_booking / list_bookings
- 冲突时 HTTP 409，错误体 detail.code = BOOKING_CONFLICT

## 5. 硬约束（必须 reject）

- 结束时间必须晚于开始时间（相等或更早 → 拒绝）
- 同一会议室时段不可重叠；首尾相接（上一段 end == 下一段 start）允许
- 只能订 is_active=true 的会议室；停用房拒绝
- 不同会议室同时段互不影响
- domain 规矩检查必须是纯函数，禁止调用 db / 读文件
- CreateBookingRequest 仅为 {room_id, title, booker, start_at, end_at}；禁止含 id / slot / begin_time
- 冲突 HTTP 409 时错误体为 {"detail": {"code": "BOOKING_CONFLICT", "message": "..."}}
- API 路由挂在 /api/v1 前缀下（rooms、bookings）
- 前端不自算冲突；只展示后端错误码与文案
- 字段名写死：禁止 start/begin_time 等漂移
- list_bookings(self, room_id=None)：room_id 为 None 时列全部（不加 WHERE），非 None 时按房间过滤；禁止设成必传或列全部时 raise 400
- API 端点禁止 except Exception 兜底吞掉所有异常变 500（会掩盖 409/422）；只捕获业务异常（ValueError→409），HTTPException 透传
- 冲突检查函数必须 raise ValueError（被 API 捕获→409）；禁止 raise 其他异常或返回 bool 由 API 判断

## 6. 推荐模式（Pattern）

- 种子会议室：≥2 启用 + ≥1 停用（如 3F-星河 / 3F-晨光 / 5F-远山 + 2F-维修中）
- 冲突时返回明确错误码，而不是静默覆盖或 500
- 分阶段落地：models → repositories → schemas → domain+test_rules → services → API+test_api → frontend
- 测试用 monkeypatch 将 meeting_order 的 DB_PATH 指到 tmp_path 再 init_db；API 测试用 TestClient(app)
- 实现依赖方前先读已有 models/domain 签名并对齐字段名与类型
- FE↔API 集成流：GET rooms → POST bookings → GET bookings 刷新；配套 test_fe_backend_flow + FE 接线契约（datetime-local、rooms 下拉、提交后 setBookings）

## 7. 反模式（AntiPattern）

- 在 API 层写复杂预订规矩（应放 domain；编排经 services；持久化经 repositories）
- 在 api/services 直接 sqlite3.connect（须经 repositories.factory）
- 页面自己判断撞车当唯一防线
- domain 访问库
- 发明不存在的字段（team、slot、begin_time、active）
- 用 CreateBookingRequest 当含 id 的 response，或字段名漂移
- 测试里写死生产 DB 路径、或不 monkeypatch 导致污染/串库
- 测试用 patch('meeting_order.api.bookings.create_booking') mock 路由函数（FastAPI 注册时已捕获原函数引用，patch 不生效；应 patch repository 或用真实端点）
- API 端点用 except Exception 兜底吞 409 变 500
- list_bookings 设成 room_id 必传、列全部时 raise 400/500
- 测试断言用 client.get('/') 的 url 去检查 /api/v1（根路径没有 /api/v1，应用真实接口路径 /api/v1/rooms）

## 8. 验收标准

1. 能查看会议室名单（含启用/停用）
2. 能提交合法预订并刷新后仍在
3. 冲突/坏时间/停用房被拒绝，前端红字展示原因；列表无脏数据
4. 首尾相接可以订
5. pytest（domain/api）与前端 vite build 通过

## 9. 非目标 / 范围外

- 审批流
- 登录权限 / 部门隔离
- 消息通知 / 会议邀请
- 按人数卡容量（容量只展示）
- 复杂日历、拖拽改期
"""

ACCEPTANCE = """# Meeting Order Acceptance Checklist

- [ ] GET /api/v1/rooms 会议室列表（含启用/停用）
- [ ] POST /api/v1/bookings 合法预订成功
- [ ] POST 重叠预订返回 409 + BOOKING_CONFLICT
- [ ] 首尾相接可订；坏时间/停用房被拒
- [ ] BookingPage 可提交与展示列表
- [ ] 冲突红字提示；RulesPanel 展示规矩摘要
- [ ] pytest -q tests/meeting_order 通过
- [ ] cd frontend && npm run build 通过
"""


def _w(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def scaffold_meeting_order(workspace: Path) -> Path:
    root = Path(workspace).resolve()
    root.mkdir(parents=True, exist_ok=True)

    cfg = WorkspaceConfig(
        name="meeting_order",
        root=root,
        app_entry="meeting_order.main:app",
        test_cmd="pytest -q tests/meeting_order",
        allowed_path_prefixes=[
            "backend/",
            "frontend/src/",
            "frontend/public/",
            "frontend/index.html",
            "tests/",
            "docs/",
            "data/",
            "acceptance/",
        ],
    )
    cfg.save()

    _w(
        root / "requirements.txt",
        "fastapi>=0.110\nuvicorn>=0.27\npydantic>=2.0\npytest>=7.0\nhttpx>=0.27\n",
    )
    _w(
        root / ".env.example",
        "MEETING_DB_BACKEND=sqlite\nMEETING_DB=data/meeting_order.db\nMEETING_MYSQL_DSN=\n",
    )
    _w(
        root / "README.md",
        "# Meeting Order\n\nFastAPI + React 会议室预订系统（由 democode CLI scaffold）。\n\n"
        "## 开发\n\n```bash\n"
        "# 后端\ncd backend && PYTHONPATH=src uvicorn meeting_order.main:app --reload --port 8000\n\n"
        "# 前端\ncd frontend && npm install && npm run dev\n```\n",
    )
    _w(root / "docs" / "business_brief.md", BUSINESS_BRIEF)
    pkg_docs = Path(__file__).resolve().parents[1] / "docs"
    arch_src = pkg_docs / "meeting_architecture_brief.md"
    schema_src = pkg_docs / "meeting_schema.json"
    if schema_src.exists():
        _w(root / "docs" / "meeting_schema.json", schema_src.read_text(encoding="utf-8"))
        _w(
            root / ".ontology_agent" / "meeting_schema.json",
            schema_src.read_text(encoding="utf-8"),
        )
    if arch_src.exists():
        _w(root / "docs" / "architecture_brief.md", arch_src.read_text(encoding="utf-8"))
    else:
        _w(
            root / "docs" / "architecture_brief.md",
            "# 架构说明\n\n## 分层\n\n- API → Service → Repository\n\n"
            "## 写路径与验证\n\n- DiffApplier + VerifyGate，失败回滚\n\n"
            "## 写范围\n\n- 遵守 workspace.toml\n\n"
            "## 反模式\n\n- 不要把业务规则写进架构记忆\n",
        )
    _w(root / "acceptance" / "checklist.md", ACCEPTANCE)
    _w(
        root / "data" / "seed_rooms.json",
        '[\n'
        '  {"name": "3F-星河", "capacity": 8, "is_active": true},\n'
        '  {"name": "3F-晨光", "capacity": 6, "is_active": true},\n'
        '  {"name": "5F-远山", "capacity": 12, "is_active": true},\n'
        '  {"name": "2F-维修中", "capacity": 4, "is_active": false}\n'
        ']\n',
    )

    # backend stubs
    pkg = root / "backend" / "src" / "meeting_order"
    _w(pkg / "__init__.py", '"""Meeting order backend package."""\n')
    _w(
        pkg / "config.py",
        "from pathlib import Path\n"
        "import os\n"
        "ROOT = Path(__file__).resolve().parents[3]\n"
        'DB_BACKEND = os.environ.get("MEETING_DB_BACKEND", "sqlite")\n'
        'DB_PATH = Path(os.environ.get("MEETING_DB", str(ROOT / "data" / "meeting_order.db")))\n'
        'MYSQL_DSN = os.environ.get("MEETING_MYSQL_DSN", "")\n'
        "\n"
        "# API URL 规范化：全局前缀只定义一次；router 只写资源段；main 用此常量挂载\n"
        'API_V1_PREFIX = "/api/v1"\n',
    )
    _w(
        pkg / "db.py",
        '"""兼容入口：请使用 meeting_order.repositories.factory。"""\n'
        "from meeting_order.repositories.factory import init_db, get_repository\n\n"
        '__all__ = ["init_db", "get_repository"]\n',
    )
    _w(
        pkg / "repositories" / "__init__.py",
        "from .factory import get_repository, init_db\n\n__all__ = ['get_repository', 'init_db']\n",
    )
    _w(pkg / "repositories" / "base.py", '"""MeetingRepository Protocol (stub)."""\n')
    _w(pkg / "repositories" / "sqlite_repo.py", '"""SQLite repository (stub)."""\n')
    _w(pkg / "repositories" / "mysql_repo.py", '"""MySQL repository (stub)."""\n')
    _w(
        pkg / "repositories" / "factory.py",
        "def init_db() -> None:\n"
        "    pass\n\n"
        "def get_repository():\n"
        '    raise NotImplementedError("implement repositories")\n',
    )
    _w(pkg / "services" / "__init__.py", "")
    _w(pkg / "services" / "room_service.py", '"""RoomService (stub)."""\n')
    _w(pkg / "services" / "booking_service.py", '"""BookingService (stub)."""\n')
    _w(
        pkg / "schemas" / "booking.py",
        "from pydantic import BaseModel, Field\n\n"
        "class CreateBookingRequest(BaseModel):\n"
        "    room_id: int\n"
        "    title: str = Field(min_length=1)\n"
        "    booker: str = Field(min_length=1)\n"
        "    start_at: str = Field(min_length=1)\n"
        "    end_at: str = Field(min_length=1)\n",
    )
    _w(
        pkg / "schemas" / "__init__.py",
        "from .booking import CreateBookingRequest\n\n__all__ = ['CreateBookingRequest']\n",
    )
    _w(
        pkg / "models" / "__init__.py",
        "from .room import Room\nfrom .booking import Booking\n\n__all__ = ['Room', 'Booking']\n",
    )
    _w(
        pkg / "models" / "room.py",
        "from dataclasses import dataclass\n"
        "from typing import Optional\n\n"
        "@dataclass\n"
        "class Room:\n"
        "    id: Optional[int]\n"
        "    name: str\n"
        "    capacity: int\n"
        "    is_active: bool = True\n",
    )
    _w(
        pkg / "models" / "booking.py",
        "from dataclasses import dataclass\n"
        "from typing import Optional\n\n"
        "@dataclass\n"
        "class Booking:\n"
        "    id: Optional[int]\n"
        "    room_id: int\n"
        "    title: str\n"
        "    booker: str\n"
        "    start_at: str\n"
        "    end_at: str\n",
    )
    _w(pkg / "domain" / "__init__.py", "")
    _w(
        pkg / "domain" / "rules.py",
        '"""Booking conflict rules (stub)."""\n\n'
        "def validate_time_range(start_at: str, end_at: str) -> None:\n"
        '    """Raise ValueError if end_at is not after start_at."""\n'
        "    return None\n\n"
        "def check_no_overlap(room_id: int, start_at: str, end_at: str, existing) -> None:\n"
        '    """Raise ValueError if same-room intervals overlap (abut allowed)."""\n'
        "    return None\n\n"
        "def check_room_active(room) -> None:\n"
        '    """Raise ValueError if room is inactive."""\n'
        "    return None\n",
    )
    _w(pkg / "api" / "__init__.py", "")
    _w(
        pkg / "api" / "rooms.py",
        "from fastapi import APIRouter\n"
        'router = APIRouter(prefix="/rooms", tags=["rooms"])\n\n'
        '@router.get("")\n'
        "def list_rooms():\n"
        "    return []\n",
    )
    _w(
        pkg / "api" / "bookings.py",
        "from fastapi import APIRouter\n"
        'router = APIRouter(prefix="/bookings", tags=["bookings"])\n\n'
        '@router.get("")\n'
        "def list_bookings():\n"
        "    return []\n\n"
        '@router.post("")\n'
        "def create_booking(payload: dict):\n"
        "    return payload\n",
    )
    _w(
        pkg / "main.py",
        '''"""FastAPI entry."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from meeting_order.api import bookings, rooms
from meeting_order.config import API_V1_PREFIX
from meeting_order.repositories.factory import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Meeting Order", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# 前缀只挂载一次；router 自身只有 /rooms、/bookings
app.include_router(rooms.router, prefix=API_V1_PREFIX)
app.include_router(bookings.router, prefix=API_V1_PREFIX)


@app.get("/health")
def health():
    return {"ok": True}
''',
    )

    # tests
    _w(root / "tests" / "meeting_order" / "test_rules.py", "def test_rules_stub():\n    assert True\n")
    _w(
        root / "tests" / "meeting_order" / "test_api.py",
        '''"""API 集成测试：rooms / bookings / 409。保留此 fixture，只补断言。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """每个测试独立 tmp DB，禁止 session 级共享、禁止用生产库。"""
    import meeting_order.config as config
    from meeting_order.main import app
    from meeting_order.repositories.factory import init_db
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    init_db()
    with TestClient(app) as c:
        yield c


def test_rooms_endpoint(client):
    res = client.get("/api/v1/rooms")
    assert res.status_code == 200
    rooms = res.json()
    assert isinstance(rooms, list) and len(rooms) >= 2
''',
    )
    _w(
        root / "tests" / "meeting_order" / "test_api_smoke.py",
        '''from fastapi.testclient import TestClient
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "src"))
from meeting_order.main import app

client = TestClient(app)

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
''',
    )
    _w(
        root / "tests" / "meeting_order" / "test_fe_wire_contract.py",
        '''"""前端接线契约：不启浏览器，专抓列表/控件/刷新假活。"""
from __future__ import annotations
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
IFCLUB = Path(__file__).resolve().parents[4]
if str(IFCLUB) not in sys.path:
    sys.path.insert(0, str(IFCLUB))
from harness.fe_api_contract import check_fe_api_contract  # noqa: E402

def test_fe_api_wire_contract():
    result = check_fe_api_contract(ROOT)
    assert result.ok, result.summary()

@pytest.mark.parametrize(
    "rel,needle",
    [
        ("frontend/src/components/BookingForm.tsx", \'type="datetime-local"\'),
        ("frontend/src/components/BookingForm.tsx", "FormData"),
        ("frontend/src/pages/BookingPage.tsx", "rooms={rooms}"),
        ("frontend/src/pages/BookingPage.tsx", "refreshBookings"),
        ("frontend/src/api/client.ts", "joinApiPath"),
    ],
)
def test_fe_wire_needles(rel: str, needle: str):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert needle in text, f"{rel} 缺少 {needle!r}"

def test_fe_no_double_api_prefix():
    page = (ROOT / "frontend/src/pages/BookingPage.tsx").read_text(encoding="utf-8")
    assert \'apiGet("/api/v1/\' not in page
    assert \'"/rooms"\' in page and \'"/bookings"\' in page
''',
    )
    _w(
        root / "tests" / "meeting_order" / "test_api_url_contract.py",
        '''"""API URL 规范化契约。"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
IFCLUB = Path(__file__).resolve().parents[4]
if str(IFCLUB) not in sys.path:
    sys.path.insert(0, str(IFCLUB))
from harness.api_url_contract import check_api_url_contract  # noqa: E402

def test_api_url_contract():
    result = check_api_url_contract(ROOT)
    assert result.ok, result.summary()
''',
    )
    _w(
        root / "tests" / "meeting_order" / "test_factory_contract.py",
        '''"""factory 契约：init_db 必须种子；get_repository 必须尊重 monkeypatch（禁全局缓存）。"""
import pytest


def test_init_db_seeds_rooms(tmp_path, monkeypatch):
    import meeting_order.config as config
    from meeting_order.repositories.factory import init_db, get_repository
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "a.db"))
    init_db()
    rooms = get_repository().list_rooms()
    assert len(rooms) >= 2, "init_db 后必须有种子房间"


def test_get_repository_respects_monkeypatch(tmp_path, monkeypatch):
    import meeting_order.config as config
    from meeting_order.repositories.factory import init_db, get_repository
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "b.db"))
    init_db()
    repo = get_repository()
    # 新库应只有种子房间，无残留预订
    assert len(repo.list_rooms()) >= 2
    assert repo.list_bookings() == [] or len(repo.list_bookings()) == 0
''',
    )
    _w(
        root / "tests" / "meeting_order" / "test_fe_backend_flow.py",
        '''"""FE↔API 集成流：GET rooms → POST bookings → GET bookings 刷新。"""
from __future__ import annotations
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

@pytest.fixture()
def client(tmp_path, monkeypatch):
    import meeting_order.config as config
    from meeting_order.main import app
    from meeting_order.repositories.factory import init_db
    db = tmp_path / "fe_flow.db"
    monkeypatch.setattr(config, "DB_PATH", db)
    init_db()
    with TestClient(app) as c:
        yield c

def test_fe_backend_rooms_then_book_then_refresh(client: TestClient):
    rooms_res = client.get("/api/v1/rooms")
    assert rooms_res.status_code == 200
    rooms = rooms_res.json()
    assert isinstance(rooms, list) and len(rooms) >= 2
    for key in ("id", "name", "capacity", "is_active"):
        assert key in rooms[0]
    active = [r for r in rooms if r.get("is_active")]
    assert active
    assert client.get("/api/v1/bookings").status_code == 200
    room_id = active[0]["id"]
    create = client.post(
        "/api/v1/bookings",
        json={
            "room_id": room_id,
            "title": "前端联调会",
            "booker": "集成测试",
            "start_at": "2026-10-01T09:00:00",
            "end_at": "2026-10-01T10:00:00",
        },
    )
    assert create.status_code in (200, 201), create.text
    bookings = client.get("/api/v1/bookings").json()
    assert any(b.get("title") == "前端联调会" for b in bookings)
    conflict = client.post(
        "/api/v1/bookings",
        json={
            "room_id": room_id,
            "title": "撞车会",
            "booker": "乙",
            "start_at": "2026-10-01T09:30:00",
            "end_at": "2026-10-01T10:30:00",
        },
    )
    assert conflict.status_code == 409
    detail = conflict.json()["detail"]
    assert detail["code"] == "BOOKING_CONFLICT"
    assert detail.get("message")

def test_fe_source_mentions_refresh_after_post():
    page = Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "BookingPage.tsx"
    text = page.read_text(encoding="utf-8")
    assert "setBookings" in text
    assert "refreshBookings" in text or text.count("/bookings") >= 2
''',
    )

    # frontend
    fe = root / "frontend"
    _w(
        fe / "package.json",
        '''{
  "name": "meeting-order-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.0"
  }
}
''',
    )
    _w(
        fe / "vite.config.ts",
        '''import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
''',
    )
    _w(
        fe / "tsconfig.json",
        '''{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "strict": true,
    "jsx": "react-jsx",
    "noEmit": true
  },
  "include": ["src"]
}
''',
    )
    _w(
        fe / "index.html",
        """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>会议室预订</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
""",
    )
    _w(
        fe / "src" / "main.tsx",
        '''import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
''',
    )
    _w(
        fe / "src" / "App.tsx",
        '''import BookingPage from "./pages/BookingPage";

export default function App() {
  return (
    <div className="app">
      <header>
        <h1>会议室预订</h1>
      </header>
      <main>
        <BookingPage />
      </main>
    </div>
  );
}
''',
    )
    _w(
        fe / "src" / "styles.css",
        """:root {
  --bg: #f4f6f8;
  --surface: #ffffff;
  --text: #1a1d21;
  --muted: #6b7280;
  --border: #e5e7eb;
  --accent: #0f766e;
  --danger: #b91c1c;
  --danger-bg: #fef2f2;
  --radius: 8px;
  --space: 1rem;
  --font: "Segoe UI", "PingFang SC", "Hiragino Sans GB", sans-serif;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: var(--font);
  background: var(--bg);
  color: var(--text);
}

.app header {
  display: flex;
  align-items: center;
  padding: var(--space) 1.5rem;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}

.app main {
  padding: 1.5rem;
  max-width: 960px;
  margin: 0 auto;
}

.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--space);
  margin-bottom: var(--space);
}

.muted { color: var(--muted); }

.err {
  color: var(--danger);
  background: var(--danger-bg);
  border: 1px solid #fecaca;
  border-radius: var(--radius);
  padding: 0.75rem 1rem;
  margin: 0 0 var(--space);
}

form.booking-form {
  display: grid;
  gap: 0.75rem;
}

form.booking-form label {
  display: grid;
  gap: 0.25rem;
  font-size: 0.9rem;
}

form.booking-form input,
form.booking-form select {
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  font: inherit;
}

button {
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 0.55rem 1rem;
  font: inherit;
  cursor: pointer;
}

ul.list {
  list-style: none;
  padding: 0;
  margin: 0;
}

ul.list li {
  padding: 0.6rem 0;
  border-bottom: 1px solid var(--border);
}

.badge-off {
  color: var(--danger);
  font-size: 0.85rem;
}
""",
    )
    _w(
        fe / "src" / "api" / "client.ts",
        'export const apiBase = "/api/v1";\n\n'
        "/** path 只写 /rooms、/bookings；已带 /api/v1 则不再重复拼接。 */\n"
        "export function joinApiPath(path: string): string {\n"
        "  const p = (path || '').trim();\n"
        "  if (!p) return apiBase;\n"
        "  const normalized = p.startsWith('/') ? p : `/${p}`;\n"
        "  if (normalized === apiBase || normalized.startsWith(`${apiBase}/`)) return normalized;\n"
        "  if (normalized.startsWith('/api/')) return normalized;\n"
        "  return `${apiBase}${normalized}`;\n"
        "}\n\n"
        "async function raiseForResponse(res: Response): Promise<never> {\n"
        "  const text = await res.text();\n"
        "  try {\n"
        "    const data = JSON.parse(text);\n"
        "    const detail = data?.detail;\n"
        "    if (typeof detail === 'string') throw new Error(detail);\n"
        "    if (detail?.message) throw new Error(String(detail.message));\n"
        "  } catch (e) {\n"
        "    if (e instanceof Error && e.message && !e.message.startsWith('{')) throw e;\n"
        "  }\n"
        "  throw new Error(text || `HTTP ${res.status}`);\n"
        "}\n\n"
        "export async function apiGet<T>(path: string): Promise<T> {\n"
        "  const res = await fetch(joinApiPath(path));\n"
        "  if (!res.ok) await raiseForResponse(res);\n"
        "  return res.json();\n"
        "}\n\n"
        "export async function apiPost<T>(path: string, body: unknown): Promise<T> {\n"
        "  const res = await fetch(joinApiPath(path), {\n"
        '    method: "POST",\n'
        '    headers: { "Content-Type": "application/json" },\n'
        "    body: JSON.stringify(body),\n"
        "  });\n"
        "  if (!res.ok) await raiseForResponse(res);\n"
        "  return res.json();\n"
        "}\n",
    )
    _w(
        fe / "src" / "types" / "index.ts",
        "export type Room = {\n"
        "  id: number;\n"
        "  name: string;\n"
        "  capacity: number;\n"
        "  is_active: boolean;\n"
        "};\n\n"
        "export type Booking = {\n"
        "  id?: number | null;\n"
        "  room_id: number;\n"
        "  title: string;\n"
        "  booker: string;\n"
        "  start_at: string;\n"
        "  end_at: string;\n"
        "};\n\n"
        "export type CreateBookingRequest = {\n"
        "  room_id: number;\n"
        "  title: string;\n"
        "  booker: string;\n"
        "  start_at: string;\n"
        "  end_at: string;\n"
        "};\n",
    )
    _w(
        fe / "src" / "pages" / "BookingPage.tsx",
        '''import { useCallback, useEffect, useState } from "react";
import ErrorBanner from "../components/ErrorBanner";
import BookingForm from "../components/BookingForm";
import BookingList from "../components/BookingList";
import RoomList from "../components/RoomList";
import RulesPanel from "../components/RulesPanel";
import { apiGet, apiPost } from "../api/client";
import type { Booking, CreateBookingRequest, Room } from "../types";

export default function BookingPage() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [error, setError] = useState("");

  const refreshBookings = useCallback(async () => {
    const data = await apiGet<Booking[]>("/bookings");
    setBookings(data);
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const [r, b] = await Promise.all([
          apiGet<Room[]>("/rooms"),
          apiGet<Booking[]>("/bookings"),
        ]);
        setRooms(r);
        setBookings(b);
      } catch {
        setError("加载失败：请确认后端 /api/v1 可用");
      }
    })();
  }, []);

  const onSubmit = async (payload: CreateBookingRequest) => {
    setError("");
    try {
      await apiPost<Booking>("/bookings", payload);
      await refreshBookings();
    } catch (e) {
      setError(e instanceof Error ? e.message : "预订失败");
    }
  };

  return (
    <div>
      <ErrorBanner message={error} />
      <div className="panel">
        <h2>提交预订</h2>
        <BookingForm rooms={rooms} onSubmit={onSubmit} />
      </div>
      <div className="panel">
        <h2>会议室</h2>
        <RoomList rooms={rooms} />
      </div>
      <div className="panel">
        <h2>已有预订</h2>
        <BookingList bookings={bookings} />
      </div>
      <RulesPanel />
    </div>
  );
}
''',
    )
    _w(
        fe / "src" / "components" / "ErrorBanner.tsx",
        "export default function ErrorBanner({ message }: { message: string }) {\n"
        "  if (!message) return null;\n"
        '  return <p className="err" role="alert">{message}</p>;\n'
        "}\n",
    )
    _w(
        fe / "src" / "components" / "BookingForm.tsx",
        '''import type { CreateBookingRequest, Room } from "../types";

type Props = {
  rooms: Room[];
  onSubmit: (data: CreateBookingRequest) => void | Promise<void>;
};

function toApiDateTime(value: string): string {
  const v = (value || "").trim();
  return v.length === 16 ? `${v}:00` : v;
}

export default function BookingForm({ rooms, onSubmit }: Props) {
  return (
    <form
      className="booking-form"
      onSubmit={async (e) => {
        e.preventDefault();
        const fd = new FormData(e.currentTarget);
        await onSubmit({
          room_id: Number(fd.get("room_id")),
          title: String(fd.get("title") || "").trim(),
          booker: String(fd.get("booker") || "").trim(),
          start_at: toApiDateTime(String(fd.get("start_at") || "")),
          end_at: toApiDateTime(String(fd.get("end_at") || "")),
        });
      }}
    >
      <label>
        会议室
        <select name="room_id" required defaultValue="">
          <option value="" disabled>
            请选择
          </option>
          {rooms
            .filter((r) => r.is_active)
            .map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
        </select>
      </label>
      <label>
        会议主题
        <input name="title" placeholder="主题" required />
      </label>
      <label>
        预订人
        <input name="booker" placeholder="姓名" required />
      </label>
      <label>
        开始时间
        <input name="start_at" type="datetime-local" required />
      </label>
      <label>
        结束时间
        <input name="end_at" type="datetime-local" required />
      </label>
      <button type="submit">提交预订</button>
    </form>
  );
}
''',
    )
    _w(
        fe / "src" / "components" / "BookingList.tsx",
        '''import type { Booking } from "../types";

export default function BookingList({ bookings }: { bookings: Booking[] }) {
  if (!bookings.length) {
    return <p className="muted">暂无预订</p>;
  }
  return (
    <ul className="list">
      {bookings.map((b, i) => (
        <li key={b.id ?? i}>
          房间 #{b.room_id} · {b.title} · {b.booker} · {b.start_at} → {b.end_at}
        </li>
      ))}
    </ul>
  );
}
''',
    )
    _w(
        fe / "src" / "components" / "RoomList.tsx",
        '''import type { Room } from "../types";

export default function RoomList({ rooms }: { rooms: Room[] }) {
  if (!rooms.length) {
    return <p className="muted">暂无会议室（待初始化）</p>;
  }
  return (
    <ul className="list">
      {rooms.map((r) => (
        <li key={r.id}>
          {r.name} · 约 {r.capacity} 人{" "}
          {!r.is_active && <span className="badge-off">停用</span>}
        </li>
      ))}
    </ul>
  );
}
''',
    )
    _w(
        fe / "src" / "components" / "RulesPanel.tsx",
        '''export default function RulesPanel() {
  return (
    <div className="panel">
      <h2>预订规矩</h2>
      <ul>
        <li>结束时间必须晚于开始时间</li>
        <li>同一会议室时段不能重叠（首尾相接可以）</li>
        <li>只能订启用中的会议室</li>
        <li>冲突由系统拒绝，页面只负责提示</li>
      </ul>
    </div>
  );
}
''',
    )

    (root / ".ontology_agent" / "memory").mkdir(parents=True, exist_ok=True)
    (root / ".ontology_agent" / "arch_memory").mkdir(parents=True, exist_ok=True)
    (root / ".ontology_agent" / "backup").mkdir(parents=True, exist_ok=True)
    return root
