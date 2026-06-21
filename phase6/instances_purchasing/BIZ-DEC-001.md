---
id: BIZ-DEC-001
object_type: DecisionRecord
title: 认证阈值调整：从 30 天改为 15 天
layer: DOMAIN
tier: warm
tags:
- certification
- threshold-change
- rule-evolution
confidence: 0.9
schema_version: 2
decision: 将 BIZ-CERT-001 中的认证有效期下限从 30 天调整为 15 天，以适应快速认证更新场景
about_concepts:
- supplier-certification
- rule-change
derived_from: [biz-task-2026-06-cert-review]
status: active
domain: purchasing
---

## 背景

部分中小供应商的认证机构审批周期为 20-25 天，30 天阈值导致供应商在续证期间无法接单，产生了不必要的业务中断。

## 决策

将 BIZ-CERT-001 的阈值从 >= 30 天调整为 >= 15 天。对历史决策记录保留审计链，标记为 superseded。

## 备选

不修改阈值，改为对认证中的供应商开放豁免申请（已否决：豁免路径引入主观判断，审计困难）。
