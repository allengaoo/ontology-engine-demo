# 最小本体引擎 Demo

这是一个完整可运行的最小本体引擎实现，便于更好地理解公众号文章《工程师的本体论》系列的内容。

项目按阶段组织：
- **phase1** — 本体引擎核心（文章 5-7）
- **phase2** — Agent 交互层（文章 8-11）
- **phase3** — 记忆系统（文章 12-17）
- **phase4** — Multi-Agent 架构（文章 18-23）
- **phase5** — 意图编译与生产化（文章 24-29）
- **phase6** — 记忆本体内核（文章 29-36）
- **phase7** — 记忆感知多智能体（文章 037）

---

## 📁 目录结构

```
ontology-engine-demo/
├── README.md
├── requirements.txt
│
├── phase1/                      # 第一阶段：本体引擎（文章 5-7）
│   ├── schema/                  # YAML Schema 定义
│   ├── data/                    # 测试数据（JSON）
│   ├── logs/                    # 审计日志（运行后生成，已 gitignore）
│   ├── engine/                  # 五个核心组件
│   └── test_scenarios.py        # 三场景测试脚本
│
├── phase2/                      # 第二阶段：OAG / Agent 交互（文章 8-11）
│   ├── capability_provider.py   # Schema → Function Calling 能力清单
│   ├── llm_client.py            # 双路径 LLM / mock
│   ├── mock_agent.py            # 离线 mock Agent
│   ├── agent_gateway.py         # 发现→调用→拒绝→重试
│   ├── audit_query.py           # 决策血统审计查询
│   └── run_phase2_demo.py       # 演示入口
│
├── phase3/                      # 第三阶段：记忆系统（文章 12-17）
│   ├── memory_store.py          # 记忆存储（SQLite + 四层分类 + 生命周期）
│   ├── memory_retriever.py      # 精准检索（层级定位 + 关键词匹配）
│   ├── memory_compressor.py     # Token 预算压缩（分级保留）
│   ├── session_manager.py       # 多轮会话管理
│   ├── memory_gateway.py        # 记忆集成网关（包装 Phase 2）
│   └── run_phase3_demo.py       # 演示入口（对比无记忆 vs 有记忆）
│
├── phase4/                      # 第四阶段：Multi-Agent（文章 18-23）
│   ├── multi_agent_router.py    # Router：能力路由 + 记忆层权限隔离
│   ├── intent_agent.py          # 意图解析 Agent
│   ├── ontology_agent.py        # 规则分析 Agent
│   ├── sim_agent.py             # 约束模拟 Agent
│   ├── agent_coordinator.py     # DAG 执行 + 写冲突处理
│   └── run_phase4_demo.py       # 三 Agent 8 步协作演示
│
├── phase5/                      # 第五阶段：意图编译与生产化（文章 24-29）
│   ├── intent_compiler.py       # 自然语言 → 合法操作编译
│   ├── confidence_engine.py     # 置信度总线传播
│   ├── injection_guard.py       # Prompt Injection 防御
│   ├── schema_updater.py        # 活 Schema + 语义 MVCC
│   └── run_phase5_demo.py       # 演示入口
│
├── phase6/                      # 第六阶段：记忆本体内核（文章 29-36）
│   ├── schema/                  # 记忆本体 YAML Schema
│   ├── instances/               # code-arch 域实例
│   ├── instances_purchasing/    # purchasing 域实例
│   ├── memory_graph.py          # 图加载 + 概念索引
│   ├── memory_injector.py       # tier 预算注入 + InjectManifest
│   ├── intent_router.py         # 意图 → 域/tier/budget（034）
│   ├── federated_graph.py       # 双本体联邦（035）
│   ├── memory_gc.py             # GC / 控制平面（033）
│   └── run_e2e_demo.py          # 八步集成测试（036）
│
└── phase7/                      # 第七阶段：记忆感知多智能体（文章 037）
    ├── agent_memory_scope.py    # 智能体 × 语义域 × 层级 × 读写权限
    ├── memory_aware_coordinator.py  # 多智能体编排 + 注入 + 写回 + 计划模式
    ├── memory_aware_agents.py   # 注入清单适配器
    ├── manifest_parser.py       # 注入清单 → 约束记忆 / 模式记忆
    ├── memory_writeback.py      # 决策记录写回
    ├── coder_agent.py           # 代码生成 + 约束校验
    └── run_multi_agent_memory_demo.py  # 演示入口
```

---

## 🚀 快速开始

### 前置要求

- Python 3.8+
- **phase1**：无外部依赖（仅 Python 标准库）
- **phase2**：可选 `openai`（真实 LLM 路径）；未安装则自动 fallback 到 mock
- **phase3**：无外部依赖（使用 SQLite，Python 标准库自带）
- **phase4 / phase5**：依赖 phase1-3，无额外第三方库
- **phase6 / phase7**：依赖 phase1-5 概念；LLM 脚本可选读取 `democode/.env`

### 第一阶段：运行本体引擎

```bash
git clone https://github.com/allengaoo/ontology-engine-demo
cd ontology-engine-demo

python3 phase1/test_scenarios.py
```

预期输出三个场景：正常采购、认证过期拦截、多规则同时违反。

### 第二阶段：运行 Agent 交互演示

```bash
# 完整演示（能力清单 → Agent 任务 → 审计查询）
python3 phase2/run_phase2_demo.py

# 仅打印能力清单
python3 phase2/run_phase2_demo.py --manifest

# 仅运行审计查询
python3 phase2/run_phase2_demo.py --audit
```

**Agent 双路径**：

| 路径 | 条件 | 说明 |
|------|------|------|
| 真实 LLM | 设置 `OPENAI_API_KEY` 且安装 `openai` | Function Calling 选操作 |
| Mock 兜底 | 无 key 或调用失败 | 离线可跑，输出同构 |

```bash
export OPENAI_API_KEY=sk-...
pip install openai   # 可选
python3 phase2/run_phase2_demo.py
```

> API key 请通过环境变量或本地 `.env` 配置，**不要提交到仓库**（已在 `.gitignore` 中排除）。

### 第三阶段：运行记忆系统演示

```bash
# 完整演示（对比无记忆 vs 有记忆，推荐：需配置 LLM API key）
export LLM_API_KEY=sk-your-openai-api-key  # 或其他兼容接口
python3 phase3/run_phase3_demo.py

# 仅 token 统计，不调用 LLM（离线可用）
python3 phase3/run_phase3_demo.py --token-only

# 仅演示无记忆模式
python3 phase3/run_phase3_demo.py --no-memory

# 仅演示有记忆模式
python3 phase3/run_phase3_demo.py --with-memory
```

**记忆系统核心能力**：

| 能力 | 说明 | 对应组件 |
|------|------|---------|
| **分层存储** | CRITICAL/RULE/CONTEXT/BACKGROUND 四层分类 | `memory_store.py` |
| **生命周期管理** | HOT → WARM → COLD → ARCHIVED 状态机 | `memory_store.py` |
| **精准检索** | 层级定位优先于关键词匹配 | `memory_retriever.py` |
| **Token 压缩** | 分级预算，CRITICAL 永不丢失 | `memory_compressor.py` |
| **多轮会话** | 会话历史压缩，防止上下文膨胀 | `session_manager.py` |

**演示内容**：

1. **Token 对比**：8 轮对话，无记忆模式 token 线性增长（~3000 → ~8000），有记忆模式保持稳定（~100）
2. **推理质量对比**（需配置 LLM_API_KEY）：
   - **无记忆模式**：随着历史增长，模型会"忘记"第 1 轮确立的关键约束（Lost in Middle 效应）
   - **有记忆模式**：第 8 轮依然能准确引用第 1 轮的 CRITICAL 约束，推理一致性高

**LLM API 配置**（可选）：

```bash
export LLM_API_KEY=sk-your-key           # 必填
export LLM_MODEL=gpt-4o-mini             # 可选，默认 gpt-4o-mini
export LLM_BASE_URL=https://api.openai.com/v1  # 可选，支持兼容接口
pip install openai  # 需要安装 openai 库
```

如果不配置 LLM API key，演示会自动降级为 token 统计模式。

### 第四阶段：运行 Multi-Agent 演示

```bash
python3 phase4/run_phase4_demo.py
```

**Multi-Agent 核心能力**：

| 能力 | 说明 | 对应组件 |
|------|------|---------|
| **Router 路由** | 最小权限原则，记忆层读写隔离 | `multi_agent_router.py` |
| **专业化 Agent** | Intent / Ontology / Sim 三 Agent 分工 | `intent_agent.py` 等 |
| **DAG 执行** | 依赖声明、前置检查、循环检测 | `agent_coordinator.py` |
| **写冲突处理** | 乐观锁 + 置信度仲裁 | `agent_coordinator.py` |

演示完整 8 步协作流程：意图解析 → 规则分析 → 方案生成 → 模拟否决 → 修正 → 执行。

### 第五阶段：运行意图编译与生产化演示

```bash
python3 phase5/run_phase5_demo.py
```

**Phase 5 核心能力**：

| 能力 | 说明 | 对应组件 |
|------|------|---------|
| **意图编译** | 自然语言 → 合法操作，歧义处理 | `intent_compiler.py` |
| **置信度总线** | 跨层置信度传播与衰减 | `confidence_engine.py` |
| **注入防御** | 意图清洗 + 内核强制校验 | `injection_guard.py` |
| **活 Schema** | 不停机更新 + 语义 MVCC | `schema_updater.py` |

### 第六阶段：运行记忆本体内核与端到端演练

```bash
cd democode

# 记忆图 + 注入 + 检索
python3 phase6/run_phase6_demo.py

# 控制平面 GC（033）
python3 phase6/run_governance_demo.py

# 意图路由（034）
python3 phase6/run_intent_router_demo.py

# 双本体联邦（035）
python3 phase6/run_federation_demo.py

# 八步集成测试（036）——演进 → GC → 路由 → 联邦注入 → 校验
python3 phase6/run_e2e_demo.py
python3 phase6/run_e2e_demo.py --dry-run        # 不写盘、不调 LLM
python3 phase6/run_e2e_demo.py --strict-domains # 仅注入路由指定域
```

**Phase 6 四平面架构**：

| 平面 | 模块 |
|------|------|
| 接入 | MemoryGraph · HybridSearch · MemoryInjector |
| 演进 | schema_evolution · MigrationBatch |
| 治理 | MemoryGC · MemoryAdmin |
| 路由 | IntentRouter · FederatedGraph |

涉及 LLM 的脚本读取 `democode/.env` 中的 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`（已在 `.gitignore` 排除，勿提交）。

详见 [phase6/README.md](phase6/README.md)。

### 第七阶段：运行记忆感知多智能体

```bash
cd democode

# 仅展示三个智能体各自的注入清单
python3 phase7/run_multi_agent_memory_demo.py

# P0：叠加 Phase 4 智能体 + 决策记录写回
python3 phase7/run_multi_agent_memory_demo.py --with-agents --dry-run

# P1：计划模式（权限范围 + 注入清单预览）
python3 phase7/run_multi_agent_memory_demo.py --plan

# P1：完整有向无环图（模拟验证制衡 + 代码生成智能体）
python3 phase7/run_multi_agent_memory_demo.py --full --dry-run

# P1：023 阈值制衡在联邦记忆上完整重跑
python3 phase7/run_multi_agent_memory_demo.py --full --scenario threshold --dry-run
```

**Phase 7 核心能力**：

| 能力 | 说明 | 对应组件 |
|------|------|---------|
| **权限范围映射** | 智能体 × 语义域 × 层级 × 读写权限 | `agent_memory_scope.py` |
| **联邦注入** | 每回合按 scope 生成独立注入清单 | `memory_aware_coordinator.py` |
| **清单解析** | 注入清单 → 约束记忆 / 模式记忆 | `manifest_parser.py` |
| **制衡重试** | 模拟验证否决 → 反馈写回 → 本体修正 | `memory_aware_coordinator.py` |
| **代码校验** | 代码生成智能体 + 约束语法树检查 | `coder_agent.py` |
| **决策写回** | 每回合输出 → 决策记录（含血统） | `memory_writeback.py` |

同一任务下，意图 / 本体 / 模拟验证三个智能体拿到的注入清单**不相同**——这是记忆层与多智能体层接线的核心验证点。

详见 [phase7/README.md](phase7/README.md)。

---

## 🏗️ 架构设计（phase1）

### 核心设计原则

本引擎基于 Palantir 本体架构的核心思想，做了三个关键简化：

| Palantir组件 | 解决的问题 | Demo实现 |
| ----------- | --------- | -------------------- |
| 对象数据库 + OSS | 海量数据查询和索引 | JSON文件 + 内存加载 |
| 对象数据漏斗 | 实时数据同步 | 手动初始化数据 |
| 分布式事务 | 并发写入一致性 | 内存事务 + 单线程 |
| OMS | 元数据管理 | **YAML文件（保留）** |
| 操作服务 | 规则校验 + 写回 | **ActionEngine（保留）** |
| 审计日志 | 决策追溯 | **JSONL文件（保留）** |

### 五个核心组件

```
┌─────────────────────────────────────────────────────────┐
│                    ActionEngine                          │
│              （唯一写入入口 + 事务协调器）                  │
└────────────┬────────────────────────────┬────────────────┘
             │                            │
    ┌────────▼─────────┐         ┌───────▼────────┐
    │  SchemaLoader    │         │  ObjectStore   │
    │  (YAML定义加载)  │         │  (对象存储)    │
    └──────────────────┘         └────────────────┘
             │                            │
    ┌────────▼─────────┐         ┌───────▼────────┐
    │   RuleEngine     │         │  AuditLogger   │
    │  (规则校验)      │         │  (决策日志)    │
    └──────────────────┘         └────────────────┘
```

| 组件 | 职责 | 文件 |
|------|------|------|
| **ActionEngine** | 唯一写入入口，协调执行流程 | `engine/action_engine.py` |
| **SchemaLoader** | 加载 YAML Schema | `engine/schema_loader.py` |
| **ObjectStore** | 对象读写与内存缓存 | `engine/object_store.py` |
| **RuleEngine** | 全局规则评估 | `engine/rule_engine.py` |
| **AuditLogger** | 决策快照日志 | `engine/audit_logger.py` |

---

## 🔑 三个关键设计决策（phase1）

### 决策1：规则在写入"后"执行

全局规则检查**执行后的新状态**；前置条件是"入场券"，全局规则是"出场检查"。

### 决策2：审计日志存"快照"而不是"变更"

`decisions.jsonl` 记录决策时的完整对象快照，便于三个月后还原"AI 为什么这样决定"。

### 决策3：Schema 用 YAML 而不是 Python 类

`phase1/schema/` 下的 YAML 同时服务业务审查（人读）与引擎执行（机器读）；phase2 进一步将其转为 Agent 能力清单。

---

## 🛠️ 自定义场景

修改 `phase1/data/Supplier.json` 或 `phase1/schema/rules.yaml` 后，重新运行：

```bash
python3 phase1/test_scenarios.py
```

---

## 📄 开源协议

MIT License

---

## 💬 联系方式

- **公众号**：工程师的本体论
- **问题反馈**：提交 GitHub Issue

---

**最后更新**：2026-06-26

如果这个 Demo 对你有帮助，欢迎 Star ⭐
