---
id: CN-ARCH-002
object_type: Constraint
title: 写路径必须可回滚
layer: CROSS_CUTTING
tier: hot
tags:
- architecture
- verify
confidence: 0.95
schema_version: 1
status: active
rule_id: CN-ARCH-002
enforcement: reject
---

## HOW

Agent 改代码必须经 DiffApplier 落盘 + VerifyGate（compileall / pytest）。
验证失败必须自动回滚到改前快照，不得留下半成品。

## WHEN

任何会修改工作区文件的 EP 步骤。

## WHY

小模型输出不稳定；没有回滚的写路径不可上生产。
