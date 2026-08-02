"""Deterministic oncall app scaffold (FastAPI + React)."""

from __future__ import annotations

from pathlib import Path

from workspace_config import WorkspaceConfig


BUSINESS_BRIEF = """# 值班排班系统 - 业务说明

## 1. 目标

为研发团队提供每周值班排班能力：维护工程师名单，按规则生成一周排班，检测冲突，并在 Web 界面查看/调整。

## 2. 核心对象

- Engineer：id（可为 None 表示自增）、name、is_active；禁止 team / active / slot
- Shift：id、engineer_id、date（YYYY-MM-DD 字符串）、shift_type 仅允许 primary|backup；禁止 shift_date / engineer_name / type / slot
- Roster：仅 shifts: List[Shift]；禁止 engineers / entries / roster_entries / RosterEntry
- OnCallRule：排班硬约束与软偏好（实现落在 domain/rules，不是独立表也可以）

## 3. 对象关系

- Roster 包含多个 Shift（构造：Roster(shifts=[...])，禁止 Roster(engineers=...)）
- Shift 通过 engineer_id 关联 Engineer
- OnCallRule 约束 Roster 生成与 validate_roster

## 4. 业务动作

- create_engineer / list_engineers
- generate_week_roster（POST /api/v1/roster/generate）
- assign_shift / swap_shift（第二期可延后）
- publish_roster（第二期可延后）

## 5. 硬约束（必须 reject）

- 同一工程师同一自然日不可排两个班次
- 最大连续值班天数默认 ≤ 3
- 生成一周排班时，每一天必须至少有 1 条 shift_type=primary 的 Shift；backup 可选
- 非 is_active 工程师不可排班
- validate_roster(roster, engineers) 必须是纯函数，禁止调用 db / list_engineers / 读文件
- 创建工程师 API：请求体 CreateEngineerRequest 仅为 {name, is_active?}；禁止把 Engineer（含必填 id）直接当 request body；response 可用 Engineer
- 冲突 HTTP 409 时错误体为 {\"detail\": {\"code\": \"ROSTER_CONFLICT\", \"message\": \"...\"}}（FastAPI detail 为 dict）
- generate_week(week_start, engineers) → Roster；active 工程师不足/为空时抛 RuleViolation，禁止对空列表取模导致 ZeroDivisionError
- API 路由必须挂在 /api/v1 前缀下（engineers、roster）
- 测试与生产代码中的 shift_type 只能是 primary 或 backup，禁止自造 oncall/main/duty 等值导致「No primary shift」类断言失败

## 6. 推荐模式（Pattern）

- 周循环排班：按 active 工程师 round-robin，每天先排 primary，再按需排 backup
- 冲突时返回明确错误码，而不是静默覆盖或 500
- 排班冲突/校验失败时前端只展示后端错误码与文案，不在前端重算规则
- 分阶段落地：models → repositories → schemas → rules+test_rules → scheduler+test_scheduler → services → API+test_api → frontend
- 测试用 monkeypatch 将 oncall.db.DB_PATH（或 config.DB_PATH）指到 tmp_path 再 init_db；API 测试用 TestClient(app)
- 实现依赖方前先读已有 models/rules/scheduler 签名并对齐字段名与类型
- test_scheduler：≥3 名 active 时 generate_week 成功且每天有 primary；0 名 active 时断言抛 RuleViolation
- test_api_roster：POST /api/v1/roster/generate 成功返回 shifts；可构造冲突场景期望 409 + detail.code

## 7. 反模式（AntiPattern）

- 在 API 层写复杂排班规则（应放 domain；编排经 services；持久化经 repositories）
- 在 api/services 直接 sqlite3.connect（须经 repositories.factory）
- 忽略冲突继续保存
- 把排班硬约束只写在前端或注释里、后端不校验
- 发明不存在的领域类型或字段（RosterEntry、Roster.engineers、Shift.slot、Engineer.team）
- 为「一次改完」重写已稳定/已 freeze 的 models 字段名
- 用 CreateEngineerRequest 当 response_model，或 GET 列表却返回 Roster
- 测试里写死生产 DB 路径、或不 monkeypatch 导致污染/串库
- generate 成功却返回空 shifts，或把 week_start 校验失败当成 409 冲突

## 8. 验收标准

1. 能创建工程师（API + EngineersPage）
2. 能生成一周排班（API + RosterWeekPage），且每天有 primary
3. 冲突规则触发失败且前端展示错误码
4. 能查询工程师列表与周视图
5. pytest（rules/scheduler/api）与前端 vite build 通过

## 9. 非目标 / 范围外

- 复杂权限/SSO
- 移动端原生 App
- 自动与日历系统双向同步（第一期不做）
"""

ACCEPTANCE = """# Oncall Acceptance Checklist

- [ ] POST /api/v1/engineers 创建工程师
- [ ] GET /api/v1/engineers 列表
- [ ] POST /api/v1/roster/generate 生成一周排班
- [ ] 冲突场景返回 409 + code
- [ ] EngineersPage 可增删改查
- [ ] RosterWeekPage 展示周视图
- [ ] pytest -q tests/oncall 通过
- [ ] cd frontend && npm run build 通过
"""


def _w(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def scaffold_oncall(workspace: Path) -> Path:
    root = Path(workspace).resolve()
    root.mkdir(parents=True, exist_ok=True)

    cfg = WorkspaceConfig(
        name="oncall",
        root=root,
        app_entry="oncall.main:app",
        test_cmd="pytest -q tests/oncall",
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

    _w(root / "requirements.txt", "fastapi>=0.110\nuvicorn>=0.27\npydantic>=2.0\npytest>=7.0\nhttpx>=0.27\n")
    _w(root / ".env.example", "ONCALL_DB=data/oncall.db\n")
    _w(root / "README.md", "# Oncall\n\nFastAPI + React 值班排班系统（由 democode CLI scaffold）。\n\n## 开发\n\n```bash\n# 后端\ncd backend && PYTHONPATH=src uvicorn oncall.main:app --reload --port 8000\n\n# 前端\ncd frontend && npm install && npm run dev\n```\n")
    _w(root / "docs" / "business_brief.md", BUSINESS_BRIEF)
    pkg_docs = Path(__file__).resolve().parents[1] / "docs"
    arch_src = pkg_docs / "architecture_brief.md"
    schema_src = pkg_docs / "oncall_schema.json"
    if schema_src.exists():
        _w(root / "docs" / "oncall_schema.json", schema_src.read_text(encoding="utf-8"))
        # 同时放一份到 .ontology_agent，供 SchemaGate 优先读取
        _w(
            root / ".ontology_agent" / "oncall_schema.json",
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
        root / "data" / "seed_engineers.json",
        '[{"name":"Alice","is_active":true},{"name":"Bob","is_active":true},{"name":"Carol","is_active":true}]\n',
    )

    # backend stubs
    pkg = root / "backend" / "src" / "oncall"
    _w(pkg / "__init__.py", '"""Oncall backend package."""\n')
    _w(pkg / "config.py", 'from pathlib import Path\nimport os\nROOT = Path(__file__).resolve().parents[3]\nDB_BACKEND = os.environ.get("ONCALL_DB_BACKEND", "sqlite")\nDB_PATH = Path(os.environ.get("ONCALL_DB", str(ROOT / "data" / "oncall.db")))\nMYSQL_DSN = os.environ.get("ONCALL_MYSQL_DSN", "")\n')
    # 兼容旧路径：保留 db.py 转发到 repositories
    _w(pkg / "db.py", '"""兼容入口：请使用 oncall.repositories.factory。"""\nfrom oncall.repositories.factory import init_db, get_repository\n\n__all__ = ["init_db", "get_repository"]\n')
    _w(pkg / "repositories" / "__init__.py", "from .factory import get_repository, init_db\n\n__all__ = ['get_repository', 'init_db']\n")
    _w(pkg / "repositories" / "base.py", '"""OncallRepository Protocol (stub)."""\n')
    _w(pkg / "repositories" / "sqlite_repo.py", '"""SQLite repository (stub)."""\n')
    _w(pkg / "repositories" / "mysql_repo.py", '"""MySQL repository (stub)."""\n')
    _w(pkg / "repositories" / "factory.py", 'def init_db() -> None:\n    pass\n\ndef get_repository():\n    raise NotImplementedError("implement repositories")\n')
    _w(pkg / "services" / "__init__.py", "")
    _w(pkg / "services" / "engineer_service.py", '"""EngineerService (stub)."""\n')
    _w(pkg / "services" / "roster_service.py", '"""RosterService (stub)."""\n')
    _w(
        pkg / "schemas" / "engineer.py",
        "from typing import Optional\nfrom pydantic import BaseModel, Field\n\n"
        "class CreateEngineerRequest(BaseModel):\n"
        "    name: str = Field(min_length=1)\n"
        "    is_active: Optional[bool] = True\n",
    )
    _w(pkg / "schemas" / "__init__.py", "from .engineer import CreateEngineerRequest\n\n__all__ = ['CreateEngineerRequest']\n")
    _w(
        pkg / "models" / "__init__.py",
        "from .engineer import Engineer\nfrom .shift import Shift\nfrom .roster import Roster\n\n__all__ = ['Engineer', 'Shift', 'Roster']\n",
    )
    # schema-compliant stubs（SchemaGate 硬校验要求字段齐全）
    _w(
        pkg / "models" / "engineer.py",
        "from dataclasses import dataclass\n"
        "from typing import Optional\n\n"
        "@dataclass\n"
        "class Engineer:\n"
        "    id: Optional[int]\n"
        "    name: str\n"
        "    is_active: bool = True\n",
    )
    _w(
        pkg / "models" / "shift.py",
        "from dataclasses import dataclass\n"
        "from typing import Optional\n\n"
        "@dataclass\n"
        "class Shift:\n"
        "    id: Optional[int]\n"
        "    engineer_id: int\n"
        "    date: str\n"
        "    shift_type: str\n",
    )
    _w(
        pkg / "models" / "roster.py",
        "from dataclasses import dataclass, field\n"
        "from typing import List\n"
        "from .shift import Shift\n\n"
        "@dataclass\n"
        "class Roster:\n"
        "    shifts: List[Shift] = field(default_factory=list)\n",
    )
    _w(pkg / "domain" / "__init__.py", "")
    _w(pkg / "domain" / "rules.py", '"""Conflict rules (stub)."""\n\ndef check_no_double_shift(engineer_id: str, date: str, existing) -> None:\n    """Raise ValueError if conflict."""\n    return None\n')
    _w(pkg / "domain" / "scheduler.py", '"""Week roster scheduler (stub)."""\n\ndef generate_week(week_start: str, engineers: list) -> list:\n    return []\n')
    _w(pkg / "api" / "__init__.py", "")
    _w(pkg / "api" / "engineers.py", "from fastapi import APIRouter\nrouter = APIRouter(prefix=\"/engineers\", tags=[\"engineers\"])\n\n@router.get(\"\")\ndef list_engineers():\n    return []\n")
    _w(pkg / "api" / "shifts.py", "from fastapi import APIRouter\nrouter = APIRouter(prefix=\"/shifts\", tags=[\"shifts\"])\n")
    _w(pkg / "api" / "roster.py", "from fastapi import APIRouter\nrouter = APIRouter(prefix=\"/roster\", tags=[\"roster\"])\n\n@router.post(\"/generate\")\ndef generate_roster(payload: dict):\n    return {\"week_start\": payload.get(\"week_start\"), \"shifts\": []}\n")
    _w(
        pkg / "main.py",
        '''"""FastAPI entry."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from oncall.api import engineers, roster, shifts
from oncall.repositories.factory import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Oncall", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(engineers.router, prefix="/api/v1")
app.include_router(shifts.router, prefix="/api/v1")
app.include_router(roster.router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"ok": True}
''',
    )

    # tests
    _w(root / "tests" / "oncall" / "test_rules.py", "def test_rules_stub():\n    assert True\n")
    _w(root / "tests" / "oncall" / "test_scheduler.py", "def test_scheduler_stub():\n    assert True\n")
    _w(
        root / "tests" / "oncall" / "test_api_smoke.py",
        '''from fastapi.testclient import TestClient
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "src"))
from oncall.main import app

client = TestClient(app)

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
''',
    )

    # frontend
    fe = root / "frontend"
    _w(
        fe / "package.json",
        '''{
  "name": "oncall-frontend",
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
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0"
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
    _w(fe / "index.html", """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Oncall</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
""")
    _w(fe / "src" / "main.tsx", '''import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
''')
    _w(
        fe / "src" / "App.tsx",
        '''import { Link, Route, Routes } from "react-router-dom";
import EngineersPage from "./pages/EngineersPage";
import RosterWeekPage from "./pages/RosterWeekPage";
import RulesPage from "./pages/RulesPage";

export default function App() {
  return (
    <div className="app">
      <header>
        <h1>Oncall</h1>
        <nav>
          <Link to="/">周视图</Link>
          <Link to="/engineers">工程师</Link>
          <Link to="/rules">规则</Link>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<RosterWeekPage />} />
          <Route path="/engineers" element={<EngineersPage />} />
          <Route path="/rules" element={<RulesPage />} />
        </Routes>
      </main>
    </div>
  );
}
''',
    )
    _w(fe / "src" / "styles.css", "body{font-family:system-ui,sans-serif;margin:0;background:#f6f7f9;color:#222}header{display:flex;gap:1rem;align-items:center;padding:1rem 1.5rem;background:#fff;border-bottom:1px solid #e5e7eb}nav{display:flex;gap:1rem}main{padding:1.5rem}.card{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:1rem}\n")
    _w(fe / "src" / "api" / "client.ts", 'export const apiBase = "/api/v1";\n\nexport async function apiGet<T>(path: string): Promise<T> {\n  const res = await fetch(`${apiBase}${path}`);\n  if (!res.ok) throw new Error(await res.text());\n  return res.json();\n}\n\nexport async function apiPost<T>(path: string, body: unknown): Promise<T> {\n  const res = await fetch(`${apiBase}${path}`, {\n    method: "POST",\n    headers: { "Content-Type": "application/json" },\n    body: JSON.stringify(body),\n  });\n  if (!res.ok) throw new Error(await res.text());\n  return res.json();\n}\n')
    _w(fe / "src" / "types" / "index.ts", "export type Engineer = { id: number; name: string; is_active: boolean };\nexport type Shift = { id?: number | null; engineer_id: number; date: string; shift_type: string };\n")
    _w(fe / "src" / "pages" / "EngineersPage.tsx", 'export default function EngineersPage() {\n  return <div className="card"><h2>工程师</h2><p>待实现：列表与创建。</p></div>;\n}\n')
    _w(fe / "src" / "pages" / "RosterWeekPage.tsx", 'import WeekGrid from "../components/WeekGrid";\n\nexport default function RosterWeekPage() {\n  return (\n    <div className="card">\n      <h2>周视图排班</h2>\n      <WeekGrid weekStart="2026-08-03" shifts={[]} />\n    </div>\n  );\n}\n')
    _w(fe / "src" / "pages" / "RulesPage.tsx", 'export default function RulesPage() {\n  return <div className="card"><h2>规则</h2><p>硬约束来自业务说明 / inject 记忆。</p></div>;\n}\n')
    _w(fe / "src" / "components" / "ErrorBanner.tsx", "export default function ErrorBanner({ message }: { message: string }) {\n  if (!message) return null;\n  return <p className=\"err\" role=\"alert\">{message}</p>;\n}\n")
    _w(fe / "src" / "components" / "EngineerForm.tsx", "export default function EngineerForm() {\n  return <form><input placeholder=\"姓名\" /><button type=\"submit\">保存</button></form>;\n}\n")
    _w(fe / "src" / "components" / "WeekGrid.tsx", 'export default function WeekGrid({ weekStart, shifts }: { weekStart: string; shifts: { date: string; engineer_id: number; shift_type: string }[] }) {\n  return <div className="week-grid"><div className="day-cell"><strong>{weekStart}</strong><span className="muted">{shifts.length} shifts</span></div></div>;\n}\n')

    (root / ".ontology_agent" / "memory").mkdir(parents=True, exist_ok=True)
    (root / ".ontology_agent" / "arch_memory").mkdir(parents=True, exist_ok=True)
    (root / ".ontology_agent" / "backup").mkdir(parents=True, exist_ok=True)
    return root
