# Meeting Order Acceptance Checklist

- [ ] GET /api/v1/rooms 会议室列表（含启用/停用）
- [ ] POST /api/v1/bookings 合法预订成功
- [ ] POST 重叠预订返回 409 + BOOKING_CONFLICT
- [ ] 首尾相接可订；坏时间/停用房被拒
- [ ] BookingPage 可提交与展示列表
- [ ] 冲突红字提示；RulesPanel 展示规矩摘要
- [ ] pytest -q tests/meeting_order 通过
- [ ] cd frontend && npm run build 通过
