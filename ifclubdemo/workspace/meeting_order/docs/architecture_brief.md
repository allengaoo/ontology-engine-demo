# 架构说明（会议室演示 · architecture brief）

> 注入：`python3 cli.py inject-arch docs/meeting_architecture_brief.md --workspace workspace/meeting_order`  
> 语气配合白话 Session：下面用「人话 + 必要固定路径」双写，方便小模型落盘。

## 分层（必须遵守）

后端包路径：`backend/src/meeting_order/`

1. **api/** — 对外入口：收请求、回结果；只调用 services；不写规矩、不直接存取库  
2. **schemas/** — 整理提交内容（DTO）；字段名固定  
3. **services/** — 办事编排：先问 domain 规矩，再让 repositories 存取  
4. **domain/** — 纯规矩检查（时间/重叠/停用）；禁止访问库  
5. **repositories/** — 统一存取出口；默认 sqlite，可切换 mysql 同接口  
6. **models/** — Room / Booking；通过后 freeze  

依赖：`api → services → (domain | repositories) → models`

## 数据库

- `MEETING_DB_BACKEND=sqlite|mysql`（默认 sqlite）  
- 测试固定 sqlite + 临时文件  

## API URL 规范化（前后端同一条规则）

- **全局前缀只定义一次**：后端 `config.API_V1_PREFIX = "/api/v1"`  
- **router 只写资源段**：`APIRouter(prefix="/rooms")` / `"/bookings")`，禁止再写 `/api/v1`  
- **main 统一挂载**：`include_router(..., prefix=API_V1_PREFIX)`  
- **前端 `apiBase` 必须等于同一字符串**；调用只写 `"/rooms"`、`"/bookings"`  
- 禁止双写：`apiGet("/api/v1/rooms")` → 实际变成 `/api/v1/api/v1/rooms` → 404  

## 前端

- React + 单页为主：`BookingPage` + 白名单组件  
- 禁止 `@/`；禁止页面自算冲突  
- `apiGet` / `apiPost` + `joinApiPath`；遵守上方 URL 规范  

## 字段（写死）

- Room：`id,name,capacity,is_active`  
- Booking：`id,room_id,title,booker,start_at,end_at`  
- 冲突：`HTTP 409` + `detail.code=BOOKING_CONFLICT`  

## 写范围与门禁

- 只改 `backend/src/meeting_order/**`、`tests/meeting_order/**`、`frontend/src/**`、`docs/`  
- VerifyGate：compile + pytest（domain/api）+ vite build（frontend）  
- 每轮默认只改 1 个具体源文件（小模型）；失败回滚；禁止目录伪 Unit  

## 反模式

- 页面自己判断撞车当唯一防线  
- api 直接写 SQL 或规矩  
- domain 访问库  
- 字段名漂移（start/begin_time 等）  
- 前后端各自再拼一遍 `/api/v1`（双写前缀）  
