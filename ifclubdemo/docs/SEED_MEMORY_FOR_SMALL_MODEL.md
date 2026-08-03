# 小模型场景：建议放入的种子记忆

面向 **多智能体 + 动态本体 Schema + 记忆系统** 驱动 ~30B 写业务代码。  
种子记忆的原则：**把上一轮已经反复踩过的坑，提前变成 Constraint / Pattern / Anti / Schema**，而不是指望模型「自己记住」。

## 为什么要种子记忆？

| 小模型弱点 | 种子记忆对策 |
|-----------|-------------|
| 字段名漂移（Room/Booking 字段错写） | Schema 硬字段 + CN 禁造字段 |
| 集成测写飘（404、串库、500） | PAT 测法 + CN 冲突返回 409 |
| 一轮改太多文件 | 架构 CN：Unit 预算 + Impl/Test/Repair |
| 前端 `@/` / 围栏污染 | 前端 CN + ANTI |
| 失败后重复同样错误 | FAIL→ANTI 热记忆（运行时写回） |

种子（inject 前写进 brief）负责 **开局契约**；ANTI/DEC（EP 写回）负责 **过程学习**。

## A. 业务域种子（`business_brief` → `inject`）

### Constraint（必须有）

1. **`list_bookings(room_id=None)`：room_id 为 None 时不加 WHERE，返回全部** — 禁止列全部时 raise 400/500  
2. **`Room(id,name,capacity,is_active)` / `Booking(id,room_id,title,booker,start_at,end_at)`** 字段写死  
3. **`CreateBookingRequest` 当请求体** — 禁止 Booking 当 request body  
4. **409 → `detail.code=BOOKING_CONFLICT`**  
5. **`check_no_overlap` 纯函数**：冲突 raise ValueError（被 API 捕获→409）；禁止 raise 其他异常或返回 bool  
6. **API 前缀 `/api/v1`**：router 只写 `/rooms|/bookings`，main 用 prefix 挂载  
7. **API 端点禁止 `except Exception` 兜底**：会吞掉 409/422 变 500，只捕获业务异常

### Pattern（强烈建议）

1. **冲突返回明确错误码（409）**，前端只展示不重算  
2. **落地顺序**：models → repositories → schemas → rules → services → API → FE  
3. **测试**：monkeypatch `config.DB_PATH` 到 tmp，API 用 TestClient；禁止 patch 路由函数 mock（FastAPI 注册时已捕获原函数引用）  
4. **仓储只经 factory**：禁止 api/services 直接 connect  
5. 写码前对齐上游签名  

### AntiPattern（强烈建议）

1. API 层写预订规则 / 直接 SQL  
2. 发明 `BaseRoomRepository` / `repositories.booking`  
3. freeze 后仍改 models  
4. 用错 `response_model` / `CreateBookingRequest` 当 response_model  
5. 测试写死生产 DB 路径、或不 monkeypatch 导致污染/串库  
6. 测试用 `patch('...api.bookings.create_booking')` mock 路由函数（不生效）

## B. 架构域种子（`architecture_brief` → `inject-arch`）

1. 分层与写范围（禁错误路径整路径匹配）  
2. SchemaGate + freeze + Unit 预算 + 分层门禁（pytest / vite）  
3. 前端禁止 `@/`、页面/组件白名单、禁止围栏语言标签落盘  
4. Impl/Test/Repair 分轮；FAIL→ANTI  
5. DB 经 repositories；默认 sqlite，可切换 mysql  

## C. 硬 Schema（`meeting_schema.json`，机器校验）

- models 必填/禁填字段  
- schemas.CreateBookingRequest DTO 路径与字段  
- frontend pages/components 白名单  
- `domain_contracts`：同房间时间冲突、冲突→ValueError  
- `freeze_defaults.after_models`

## D. 不必预先塞进种子的（留给运行时）

| 类型 | 原因 |
|------|------|
| 具体某次 EP 的 diff / 文件内容 | 应由 DEC 写回，不是 brief |
| 某次 Vite 报错全文 | ANTI digest 即可 |
| 业务预订偏好（谁优先） | 非第一期硬约束 |
| 大段示例源码 | 易过期；用签名注入代替 |

## E. 注入后如何验收

```bash
python cli.py init-app meeting_order
python cli.py inject docs/business_brief.md --workspace workspace/meeting_order
python cli.py inject-arch docs/architecture_brief.md --workspace workspace/meeting_order
python cli.py memory list --workspace workspace/meeting_order
```

业务侧应看到多条 `CN-MEETING_ORDER-*` / `PAT-MEETING_ORDER-*` / `ANTI-MEETING_ORDER-*`；  
架构侧应看到 `CN-ARCH-*`（分层/写路径/写范围/前端）与 `PAT-*` / `ANTI-*`。
