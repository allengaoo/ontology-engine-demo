---
id: PAT-ARCH-001
object_type: Pattern
title: FastAPI + 可切换仓储 + React 标准骨架
layer: CROSS_CUTTING
tier: hot
tags:
- architecture
- meeting_order
- stack
confidence: 0.9
schema_version: 1
status: active
---

## HOW

推荐目录：
- `backend/src/meeting_order/`：api / schemas / services / domain / repositories / models
- `tests/meeting_order/`：pytest（固定 sqlite）
- `frontend/`：Vite + React + TypeScript；组件/页面白名单见 meeting_schema.json
- `docs/business_brief.md`：业务初始记忆源
- `docs/architecture_brief.md`：架构初始记忆源
- `.ontology_agent/memory/`：业务域记忆
- `.ontology_agent/arch_memory/`：架构记忆

数据库：默认 `MEETING_DB_BACKEND=sqlite`；可切换 `mysql`（同 Repository 接口）。

## WHEN

`init-app` 后扩展功能、或新工作区对齐约定时。
