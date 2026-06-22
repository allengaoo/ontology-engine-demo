# Phase 6：记忆本体内核（骨架）

用 **YAML Schema + Python 运行时** 演示记忆系统的本体化形态，对齐 Article 029–036。

## 设计原则

- **Schema 在 YAML**：ObjectType / Link / Action / Rule 声明；Python 不写 `if layer == CRITICAL`
- **实例在 Markdown front-matter**：可 git diff、可 code review
- **与 Phase 3 的关系**：机制同源（分层、检索、压缩、淘汰），存储从 SQLite 枚举升级为本体图

## 四平面架构

```
接入平面（029）  MemoryGraph · HybridSearch · MemoryInjector · InjectManifest
演进平面（031）  SchemaSnapshot · evolve_rule · MigrationBatch
治理平面（033）  MemoryGC · MemoryAdmin
路由平面（034/035） IntentRouter · FederatedGraph · FederatedInjector
```

## 目录

```
phase6/
├── schema/                      # 记忆本体 Schema
├── instances/                   # code-arch 域
├── instances_purchasing/        # purchasing 域（035）
├── ontology_registry.py
├── memory_graph.py
├── hybrid_search.py
├── memory_injector.py           # BudgetConfig.scaled()（034 路由联动）
├── memory_actions.py
├── memory_gc.py                 # 033
├── memory_admin.py              # 033
├── schema_evolution.py          # 031
├── intent_router.py             # 034
├── federated_graph.py           # 035；build_routed_domain_budgets()
├── run_*_demo.py
└── run_e2e_demo.py              # 036 集成测试
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
python3 phase6/run_e2e_demo.py --dry-run          # 不写盘、不调 LLM
python3 phase6/run_e2e_demo.py --strict-domains   # 仅注入路由指定域
```

## Phase 6 与 Phase 7 边界

| | Phase 6 | Phase 7（规划中） |
|--|---------|-------------------|
| 范围 | 记忆本体内核（Layer 4） | Multi-Agent × 记忆联动（Layer 5） |
| 编排 | 单链路 e2e | DAG + per-Agent InjectManifest |
| 入口 | `run_e2e_demo.py` | 待发布 |

**InjectManifest 是两层之间的 syscall**：Phase 6 定义接口；Phase 7 将在每个 Agent 回合调用（文章 037，代码尚未公开）。

## 阶段规划

| 阶段 | 文章 | 代码增量 |
|------|------|----------|
| 029 | 记忆本体内核 | Schema + Registry + Graph |
| 030 | Software 3.0 | 本体在 LLM OS 中的位置 |
| 031 | Schema 演进 | evolve_rule、supersede、回滚 |
| 032 | 记忆经济学 | BudgetConfig、对照实验 |
| 033 | 控制平面 | memory_gc、memory_admin |
| 034 | 调度即查询 | intent_router |
| 035 | 双本体联邦 | federated_graph |
| 036 | 端到端演练 | run_e2e_demo（路由 budget 联动） |
| 037 | Memory-Aware Multi-Agent | 规划中（Layer 4 × Layer 5 接线） |

所有涉及 LLM 的脚本读取 `democode/.env` 中的 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。
