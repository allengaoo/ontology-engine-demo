---
id: BIZ-PAT-001
object_type: PatternMemory
title: 供应商切换模式：双写过渡期
layer: DOMAIN
tier: warm
tags:
- supplier-switch
- dual-write
- migration
confidence: 0.88
schema_version: 2
about_concepts:
- supplier-migration
- procurement
- risk-management
cites_files: [src/domain/procurement_service.py]
status: active
domain: purchasing
---

## HOW

主供应商发生切换时，采用双写过渡：新旧供应商均接收订单，持续 30 天，期间监控两条路径的交付质量，确认无误后才下线旧供应商。

## WHEN

任何涉及主力供应商切换的决策前，需评估是否要走双写过渡，特别是品类占比 > 20% 的供应商。
