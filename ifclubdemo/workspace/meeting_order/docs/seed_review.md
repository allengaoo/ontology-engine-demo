# 本轮开发经验总结

## 避坑指南

### 1. 文件路径严格控制
- 只能修改 `meeting_order` 路径下的文件
- 禁止创建新包或修改非指定路径
- 所有 import 必须在已有依赖中能找到

### 2. 代码规范遵循
- 函数和变量使用 snake_case
- 类使用 PascalCase
- 单文件长度不超过 220 行
- 严格按照现有签名进行开发

### 3. 开发流程控制
- 每轮只处理一个 Unit
- 修改前必须阅读目标文件和上游签名
- 不能臆造不存在的模块或路径
- 遵守依赖顺序：api -> services -> (domain|repositories) -> models

### 4. 特殊注意事项
- `MeetingRepository` 是标准仓储接口，避免使用 `BaseRepository` 等旧名
- 数据库相关操作通过 `factory.get_repository()` 和 `init_db()` 进行
- 时间验证规则：结束时间必须晚于开始时间
- 会议室时间段不允许重叠，但首尾相接允许

### 5. 测试与验证
- 所有变更需符合 `docs/meeting_schema.json` 中定义的结构
- 验证数据模型字段是否正确（如 Room.id 为 Optional[int]）
- 确保请求参数符合 CreateBookingRequest 定义
- 注意 JSON 数据格式一致性（如 room.is_active 应为布尔值）

### 6. 问题预防
- 避免在已有失败记录基础上重复尝试相同错误模式
- 如遇结构化错误，应先理解基础架构再进行修改
- 保持对现有代码结构的尊重，不随意破坏已有设计原则

这些经验将在后续开发中持续指导我们避免常见陷阱，提高开发效率和代码质量。