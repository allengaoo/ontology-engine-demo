# 架构说明文档

## 后端结构概览

本项目采用分层架构设计，将系统划分为多个清晰的层次，以实现关注点分离和代码复用。

### 层级结构

1. **Models 层**：定义数据模型，如 Room 和 Booking 类。
2. **Schemas 层**：定义请求和响应的数据结构，如 CreateBookingRequest 和 BookingResponse。
3. **Domain 层**：包含业务逻辑规则，例如检查预订时间有效性、房间是否活跃等。
4. **Repositories 层**：提供数据访问接口，目前使用 SQLite 实现具体存储。
5. **Services 层**：协调 Domain 和 Repositories 层，处理核心业务流程。
6. **API 层**：暴露 RESTful 接口供前端调用。

### 分层原因

- **职责单一**：每一层都有明确的职责，便于维护和扩展。
- **解耦合**：各层之间通过接口通信，降低耦合度。
- **可测试性**：每层可以独立进行单元测试。
- **灵活性**：未来更换数据库或修改业务逻辑时，影响范围最小。

### 数据流向

API 层接收请求后，传递给 Services 层进行处理。Services 层调用 Domain 层的规则校验，并通过 Repositories 层访问数据。整个过程遵循从上到下的依赖关系：API → Services → Domain/Repositories → Models。

### 核心组件说明

- **MeetingRepository**：抽象基类，定义了所有数据操作方法。
- **SqliteRepository**：具体实现类，负责与 SQLite 数据库交互。
- **check_room_is_active**：确保所选房间处于激活状态。
- **check_no_overlap**：防止同一时间段内对同一房间的重复预订。
- **validate_time_range**：验证开始时间和结束时间的有效性。

这种分层方式使得系统具备良好的可读性和可维护性，同时也方便团队协作开发不同模块。