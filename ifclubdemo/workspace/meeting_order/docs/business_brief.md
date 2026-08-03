# 会议室预订系统 - 业务说明

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
