---
id: BIZ-CN-002
object_type: ConstraintMemory
title: 采购约束：单笔金额超限需二级审批
layer: CROSS_CUTTING
tier: hot
tags:
- purchasing
- approval
- amount-limit
confidence: 1.0
schema_version: 2
rule_id: BIZ-APPROVAL-001
enforcement: reject
about_concepts:
- approval-flow
- purchase-order
- amount-threshold
about_rules:
- BIZ-APPROVAL-001
status: active
domain: purchasing
---

## HOW

单笔采购金额超过 50,000 元时，必须触发二级审批流程，无法由系统自动通过。操作方需提供 approval_request_id 才能继续。

## WHEN

create_purchase_order 参数中 amount > 50000 时强制触发。
