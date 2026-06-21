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
├── instances/              # code-arch 域记忆实例（Markdown + front-matter）
├── instances_purchasing/   # purchasing 域记忆实例（035 新增，独立目录）
├── ontology_registry.py    # 加载 Schema、校验实例
├── memory_graph.py         # 加载实例、建索引、图查询
├── hybrid_search.py        # 概念/tag 检索 + 关键词降级
├── memory_injector.py      # tier 策略 + BudgetConfig + InjectManifest（032）
├── memory_actions.py       # write / deprecate（校验后写入）
├── memory_gc.py            # GC 策略：confidence_decay / tier_degrade / stale_cleanup（033）
├── memory_admin.py         # 控制平面管理：health_report / audit_query / bulk_deprecate（033）
├── schema_evolution.py     # SchemaSnapshot / migration_batch / rollback（031）
├── intent_router.py        # 意图分类 + 路由配置（034）
├── federated_graph.py      # 双本体联邦：DomainConfig / FederatedGraph / FederatedInjector（035）
├── run_phase6_demo.py      # 端到端演示入口（029）
├── run_schema_evolution_demo.py  # Schema 演进演示（031）
├── run_budget_experiment.py      # token 预算对照实验（032）
├── run_governance_demo.py        # 记忆控制平面演示（033）
├── run_intent_router_demo.py     # 调度即查询演示（034）
├── run_federation_demo.py        # 双本体联邦演示（035）
└── run_e2e_demo.py               # 完整链路端到端演练（036）
```

## 运行

```bash
cd democode
python3 phase6/run_phase6_demo.py
python3 phase6/run_schema_evolution_demo.py --rule-id ARCH-001 --to-version 2
python3 phase6/run_budget_experiment.py
python3 phase6/run_governance_demo.py
python3 phase6/run_intent_router_demo.py
python3 phase6/run_federation_demo.py
python3 phase6/run_e2e_demo.py
```

`run_budget_experiment.py` 运行 4 组预算策略对照（A-基准、B-预算不足、C-预算过剩、D-顺序错误），验证 token 分配对模型行为的影响（Article 032）。

`run_governance_demo.py` 演示三种 GC 策略（置信度衰减、tier 降级、废弃版本清理）、dry_run 决策预览与 MemoryAdmin 健康报告（Article 033）。

`run_intent_router_demo.py` 演示意图分类漏斗（四类任务）、路由配置接入联邦图检索、路由前后噪声对比（Article 034）。

`run_federation_demo.py` 演示两个语义域（code-arch、purchasing）独立加载、跨域搜索、联合注入的完整流程（Article 035）。

`run_e2e_demo.py` 打通从业务规则变更到 GovernanceAudit 汇总的完整链路，集成 031-035 全部机制（Article 036）。

所有涉及 LLM 的脚本均读取 `democode/.env` 中的 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。

## 阶段规划

| 阶段 | 文章 | 代码增量 |
|------|------|----------|
| 029 骨架 | 记忆本体内核 | Schema + Registry + Graph + inject 骨架 |
| 030 | Software 3.0 中文脉络 | 本体在 LLM OS 中的位置说明 |
| 031 | 记忆 Schema 演进 | SchemaSnapshot、迁移批次、supersede、回滚骨架 |
| 032 | 记忆经济学 | BudgetConfig、per-tier 预算执行、inject_order、4 组对照实验 |
| 033 | 控制平面：GC 与 Admin | memory_gc.py（3 种策略）、memory_admin.py（健康报告 + 审计）、run_governance_demo.py |
| 034 | 调度即查询：Router | intent_router.py（意图分类漏斗 + 路由配置）、run_intent_router_demo.py |
| 035 | 双本体联邦 | DomainConfig、FederatedGraph、FederatedInjector、instances_purchasing |
| 036 | 端到端演练 | run_e2e_demo.py 打通 phase5→phase6 完整链路，GovernanceAudit 汇总 |
