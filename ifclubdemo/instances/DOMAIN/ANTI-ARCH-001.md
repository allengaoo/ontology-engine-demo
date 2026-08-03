---
id: ANTI-ARCH-001
object_type: AntiPattern
title: 在提示词里硬编码业务规则当架构
layer: DOMAIN
tier: warm
tags:
- architecture
- anti
confidence: 0.9
schema_version: 1
status: active
---

## HOW（反模式）

把「同房间时间不可重叠」「预订时长上限」等预订规则写进 code-arch 记忆或系统提示，当作通用架构约束。

## WHEN

区分业务记忆与架构记忆时。

## WHY

业务规则应走 `inject` → domain memory；架构记忆只保留可跨业务复用的工程约束。
