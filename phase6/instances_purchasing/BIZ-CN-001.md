---
id: BIZ-CN-001
object_type: ConstraintMemory
title: 采购约束：供应商认证有效期必须满足
layer: CROSS_CUTTING
tier: hot
tags:
- purchasing
- certification
- supplier
confidence: 1.0
schema_version: 2
rule_id: BIZ-CERT-001
enforcement: reject
about_concepts:
- supplier-certification
- procurement
- validity
about_rules:
- BIZ-CERT-001
status: active
domain: purchasing
---

## HOW

发起任何采购操作时，目标供应商的认证有效期剩余天数必须 >= 30 天。不满足则拒绝操作，不允许静默通过。

## WHEN

create_purchase_order、renew_contract、approve_payment 等写操作触发前必查。
