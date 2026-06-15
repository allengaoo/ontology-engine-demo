# Phase 6：记忆本体内核（骨架）

用 **YAML Schema + Python 运行时** 演示记忆系统的本体化形态，对齐 Article 029。

## 设计原则

- **Schema 在 YAML**：ObjectType / Link / Action / Rule 声明；Python 不写 `if layer == CRITICAL`
- **实例在 Markdown front-matter**：可 git diff、可 code review
- **与 Phase 3 的关系**：机制同源（分层、检索、压缩、淘汰），存储从 SQLite 枚举升级为本体图

## 目录

```
phase6/
├── schema/                 # 记忆本体 Schema（Source of Truth）
│   ├── _config/            # layer 枚举、注入 token 预算
│   ├── objects/            # ObjectType 定义
│   ├── links/              # LinkType 声明
│   ├── actions/            # Action 声明
│   └── rules/              # Rule 声明
├── instances/              # 记忆实例（Markdown + front-matter）
├── ontology_registry.py    # 加载 Schema、校验实例
├── memory_graph.py         # 加载实例、建索引、图查询
├── hybrid_search.py        # 概念/tag 检索 + 关键词降级
├── memory_injector.py      # tier 策略 + InjectManifest
├── memory_actions.py       # write / deprecate（校验后写入）
├── schema_evolution.py     # 演进报告（骨架，030 扩展）
└── run_phase6_demo.py      # 端到端演示入口
```

## 运行

```bash
cd democode
python3 phase6/run_phase6_demo.py
```

## 阶段规划

| 阶段 | 文章 | 代码增量 |
|------|------|----------|
| 029 骨架 | 记忆本体内核 | Schema + Registry + Graph + inject 骨架 |
| 030 | 治理与控制平面 | GC、retire、schema_evolution 完整实现 |
| 031 | 调度即查询 | intent_classifier 漏斗 |
| 032 | 记忆经济学 | injection_budget 实验与对比 |
| 033 | 双本体联邦 | 第二套语义域 objects |
| 034 | 端到端演练 | 接 phase5 schema_updater 级联 |
