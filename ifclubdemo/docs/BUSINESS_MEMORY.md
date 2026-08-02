# 业务记忆（Domain Memory）说明

值班排班示例里，**业务领域记忆不是手写一堆 YAML 起步**，而是：

1. 人编写 / 修改业务说明文档 `docs/business_brief.md`
2. 执行 `python cli.py inject docs/business_brief.md`
3. 工具把说明中的约束 / 模式 / 反模式写成记忆实例，落到工作区

---

## 文件落在哪里？

默认工作区（见 `.env` 的 `IFCLUB_WORKSPACE` + `IFCLUB_APP`）：

```text
workspace/oncall/
├── docs/business_brief.md              # 业务说明（人维护）
└── .ontology_agent/
    ├── inject_report.json              # 本次 inject 审计
    └── memory/                         # ★ 业务记忆本体实例
        ├── CROSS_CUTTING/
        │   ├── CN-ONCALL-001.md        # ConstraintMemory（硬约束）
        │   └── ...
        └── DOMAIN/
            ├── PAT-ONCALL-001.md       # PatternMemory
            └── ANTI-ONCALL-001.md      # AntiPatternMemory
```

查看：

```bash
python cli.py memory list
# 或
ls workspace/oncall/.ontology_agent/memory/**/*.md
cat workspace/oncall/.ontology_agent/inject_report.json
```

---

## `business_brief.md` 哪些章节会被 inject？

| 章节关键词 | 生成类型 | 前缀 | 含义 |
|-----------|---------|------|------|
| 硬约束 | ConstraintMemory | `CN-ONCALL-*` | 必须遵守，违规应 reject |
| 推荐模式 | PatternMemory | `PAT-ONCALL-*` | 推荐实现方式 |
| 反模式 | AntiPatternMemory | `ANTI-ONCALL-*` | 禁止做法 |

每条以 Markdown 列表项 `- ...` 写成一条记忆。  
详细模板在 `init-app` 生成的 `docs/business_brief.md`。

---

## 记忆文件长什么样？

示例（inject 后自动生成）：

```markdown
---
id: CN-ONCALL-001
object_type: ConstraintMemory
title: 同一工程师同一自然日不可排两个班次
layer: CROSS_CUTTING
tier: hot
rule_id: CN-ONCALL-001
enforcement: reject
status: active
source: business_brief.md
---

## HOW
同一工程师同一自然日不可排两个班次
```

Agent 在 `run` / `fix` 时会通过联邦注入读到这些节点，约束代码生成与校验。

---

## 和架构记忆的区别

| | 业务记忆 | 架构记忆 |
|--|---------|---------|
| 命令 | `inject` | `inject-arch` |
| 源文件 | `docs/business_brief.md` | `docs/architecture_brief.md` |
| 落盘 | `.ontology_agent/memory/` | `.ontology_agent/arch_memory/`（优先）或包内 `instances/` |
| 联邦域名 | `domain` | `code-arch` |
| 内容 | 排班规则、业务动作、反模式 | 分层、写回滚、写范围等工程约束 |

两者在 EP 中同时注入（双域 Manifest）。无业务记忆时不会再回退到旧 `instances_purchasing`。

---

## 推荐工作流

```bash
# 1) 脚手架（含 business_brief + architecture_brief）
python cli.py init-app oncall

# 2) 编辑业务 / 架构说明
$EDITOR workspace/oncall/docs/business_brief.md
$EDITOR workspace/oncall/docs/architecture_brief.md

# 3) 写入两条初始记忆
python cli.py inject docs/business_brief.md
python cli.py inject-arch docs/architecture_brief.md

# 4) 确认
python cli.py memory list

# 5) 再写代码
python cli.py run --task-file acceptance/checklist.md
```

规则变更时：先改 `business_brief.md` → 再 `inject` → 再 `fix` / `run`。
