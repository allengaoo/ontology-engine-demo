---
id: CN-ARCH-001
object_type: Constraint
title: 分层边界不可破坏
layer: CROSS_CUTTING
tier: hot
tags:
- architecture
- layering
confidence: 0.95
schema_version: 1
status: active
rule_id: CN-ARCH-001
enforcement: reject
---

## HOW

应用分层（目录固定在 `backend/src/meeting_order/`）：
API（路由）→ schemas（DTO）→ Service（编排）→（domain 纯规则 | repositories 数据访问）→ models。

硬约束：
- API 不得写 SQL，不得写预订规则
- Service 不得依赖 FastAPI Request/Response
- domain 不得访问 DB / 读文件
- 业务代码通过 `repositories.factory.get_repository()` 取仓储，禁止在 api/services 直接 `sqlite3.connect`

## WHEN

新增接口、改动业务逻辑、调整数据访问时必查。

## WHY

分层被破坏后，测试与演进成本指数上升；端侧小模型更依赖清晰边界与 Harness 可校验契约。
