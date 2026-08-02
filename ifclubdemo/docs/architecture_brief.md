# 架构说明（architecture brief）

> 本文件是**架构初始记忆**的自然语言源。
> 用 `python cli.py inject-arch` 写入工作区 `.ontology_agent/arch_memory/`。
> 未 inject 时，EP 使用包内精简种子 `ifclubdemo/instances/`。

## 分层（必须遵守）

后端包路径固定为 `backend/src/oncall/`，分层如下：

1. **api/** — HTTP 路由与状态码；只接收/返回 **schemas DTO**；调用 **services**；禁止写 SQL、禁止写排班规则  
2. **schemas/** — 数据转换层（Pydantic DTO），如 `CreateEngineerRequest`；禁止夹带业务编排  
3. **services/** — 服务层：编排 domain 规则与 repositories；禁止依赖 FastAPI Request/Response  
4. **domain/** — 纯函数业务规则（`rules.py` / `scheduler.py`）；禁止访问 DB / 读文件 / 调 HTTP  
5. **repositories/** — 数据访问；接口在 `base.py`；实现可为 sqlite 或 mysql；禁止写排班规则  
6. **models/** — 领域对象（Engineer / Shift / Roster）；通过后 freeze  

依赖方向只能是：`api → services → (domain | repositories) → models`。  
`FastAPI main.py` 须在 lifespan/startup 调用 repository/`init_db()`，避免运行期无表。

## 数据库后端（可切换）

- 配置：`ONCALL_DB_BACKEND=sqlite`（默认）或 `mysql`  
- SQLite 路径：`ONCALL_DB` / `config.DB_PATH`（默认 `data/oncall.db`）  
- MySQL：`ONCALL_MYSQL_DSN`（仅当 backend=mysql）  
- 业务代码只依赖 `repositories.factory.get_repository()`，禁止在 api/services 里直接 `sqlite3.connect`  
- 测试固定使用 sqlite + tmp_path monkeypatch  

## 前端工程约定

- 技术栈：React + TypeScript + Vite；样式只用 `src/styles.css`（CSS 变量），禁止引入 UI 组件库  
- 禁止任何 `@/` 路径别名；一律相对路径 import  
- `api/client.ts` 必须提供 `apiGet` / `apiPost`，基址 `/api/v1`；经 Vite proxy 访问后端  
- 前端不得直接打开本地数据库文件；不在前端重算排班冲突  
- **页面白名单**：`pages/EngineersPage.tsx`、`pages/RosterWeekPage.tsx`、`pages/RulesPage.tsx`  
- **组件白名单**：`components/ErrorBanner.tsx`、`components/EngineerForm.tsx`、`components/WeekGrid.tsx`  
- 字段：Engineers 只用 `name` / `is_active`；Roster 展示 `engineer_id` / `date` / `shift_type`（仅 primary|backup）  
- 生成前端代码时禁止把代码围栏语言标签写入源文件  

## API 约定

- 前缀统一 `/api/v1`  
- `POST /api/v1/engineers` 请求体 `CreateEngineerRequest={name, is_active?}`  
- `POST /api/v1/roster/generate` 生成一周排班  
- 冲突返回 HTTP 409，`detail.code=ROSTER_CONFLICT`  

## 写路径与验证

- 所有代码修改必须可回滚（DiffApplier 备份；VerifyGate 失败则 rollback）  
- VerifyGate：`compileall`；domain/api/services 层跑 scoped `pytest`；frontend 层跑 `vite build`  
- 领域 Object 与 DTO 对齐 `docs/oncall_schema.json`（SchemaGate）  
- models 通过后 freeze，禁止后续 EP 改写字段  
- 每个 EP 默认 ≤2 个 Unit；Unit 的 target_path 必须是带扩展名的具体源文件  
- Impl / Test / Repair 分轮；失败回滚并写 ANTI  

## 写范围

- 遵守 `workspace.toml`  
- 后端只改 `backend/src/oncall/**`（含 api、schemas、services、domain、repositories、models、config、main）  
- 测试只改 `tests/oncall/**`  
- 前端只改 `frontend/src/**`、`frontend/public/**`、`frontend/index.html`  
- 禁止错误路径（整路径匹配）：`backend/src/main.py`；`backend/src/oncall/models.py`；`backend/src/oncall/scheduler.py`；`backend/src/oncall/api/main.py`  

## 推荐落地顺序

models → repositories(sqlite) → schemas → domain/rules+tests → domain/scheduler+tests → services → api+tests → frontend  

## 反模式

- 在 api 层写 SQL 或排班规则  
- services 依赖 FastAPI 类型  
- domain 访问 DB  
- 使用 `@/` 或发明 `team` / `slot` / `Roster.engineers` 字段  
- 只实现 mysql、测试却连不上（测试必须 sqlite）  
- models 已 freeze 后仍改 models/*  
