# ifclubdemo 架构优化计划

> 目标：演示项目既是「能跑的会议室预订单体」，又把框架核心要素钉死，提升端侧小模型 + Harness 的准确率。

## 1. 现状问题（摘要）

| 问题 | 影响 |
|------|------|
| 文档喊 API→Service→Repository，脚手架需对齐分层 | 小模型与记忆互相打架 |
| `schemas/` 空包，DTO 只写在 brief/schema JSON | CreateBookingRequest 易被发明错 |
| DB 写死 SQLite，无仓储抽象 | 无法演示「存储可替换」 |
| 前端 types 易带黑名单字段 | 误导生成；无组件白名单/风格标准 |
| SchemaGate 只校验 models | API/DTO/分层边界门禁弱 |

## 2. 锁定的目标架构

### 后端（固定目录）

```text
backend/src/meeting_order/
├── models/           # 领域对象（可 freeze）
├── schemas/          # 数据转换层（DTO / Pydantic）
├── domain/           # 纯规则：rules（无 I/O）
├── repositories/     # 数据访问抽象 + sqlite/mysql 实现
├── services/         # 服务层：编排 domain + repository
├── api/              # 路由层：只做 HTTP ↔ DTO ↔ Service
├── config.py
└── main.py           # lifespan → init_db
```

依赖方向（硬约束）：

`api → services → (domain | repositories)`；`domain` 不得 import repositories/api；`api` 不得写 SQL / 预订规则。

### 数据库灵活性

- `MEETING_DB_BACKEND=sqlite|mysql`（默认 sqlite）
- `repositories/base.py` 定义 Protocol（MeetingRepository）
- `sqlite_repo.py` 为默认实现；`mysql_repo.py` 同接口（演示可切换）
- 测试一律 sqlite + tmp_path

### 前端标准

- 技术：React + TypeScript + Vite + 单文件 `styles.css`（CSS 变量）
- 禁止：`@/` 别名、UI 组件库、在页面重算预订冲突
- 组件白名单：`ErrorBanner`、`RoomForm`、`BookingForm`、`BookingList`
- 页面白名单：`RoomsPage`、`BookingPage`
- 字段名与 schema 对齐：`name` / `capacity` / `is_active` / `room_id` / `title` / `booker` / `start_at` / `end_at`

## 3. 框架侧改动清单

1. `docs/meeting_architecture_brief.md` — 真源分层 + FE 标准 + DB 后端开关  
2. `cli_support/scaffold_meeting_order.py` — 生成完整目录骨架与正确 FE types/`apiPost`  
3. `docs/meeting_schema.json` — 增加 DTO path、layers、frontend_allowlist  
4. `harness/schema_gate.py` — 校验 schemas DTO +（可选）前端白名单文件存在  
5. `instances/CROSS_CUTTING/CN-ARCH-001.md` / `PAT-ARCH-001.md` — 与真实目录对齐  
6. `docs/SEED_MEMORY_FOR_SMALL_MODEL.md` / `README.md` — 目标树更新  
7. `agents/coding_agent.py` — 上游签名包含 services/schemas/repositories  

## 4. 重建与验证顺序

1. 更新框架契约与脚手架  
2. `rm -rf workspace/meeting_order && python3 cli.py init-app meeting_order`  
3. 填入完整可运行实现（golden path）  
4. `inject` + `inject-arch`  
5. 验证：`pytest tests/meeting_order`、`SchemaGate`、`vite build`、API 冒烟（建房间 / 建预订 / 冲突 409）  

## 5. 非目标（本期不做）

- 完整 MySQL 生产部署与迁移工具  
- 权限 / SSO / 移动端  
- 用 LLM 自动跑完整多 session（先以契约 + golden 实现锁定标准）
