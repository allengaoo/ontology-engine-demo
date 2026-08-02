---
id: CN-ARCH-003
object_type: Constraint
title: 写范围受 workspace.toml 约束
layer: CROSS_CUTTING
tier: hot
tags:
- architecture
- sandbox
confidence: 0.95
schema_version: 1
status: active
rule_id: CN-ARCH-003
enforcement: reject
---

## HOW

只允许修改 `workspace.toml` 中 `allowed_write_globs` / `allowed_path_prefixes` 声明的路径。
默认：`src/**`、`tests/**`、`frontend/src/**`、`docs/**`、`*.py`、`*.md`。
不得改 `.env`、密钥、无关依赖锁文件（除非用户明确放开）。

## WHEN

生成 patch / 选择 target_path 时。

## WHY

端侧编码工具的安全边界是配置，不是「模型自觉」。
