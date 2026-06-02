# 最小本体引擎 Demo

这是一个完整可运行的最小本体引擎实现，便于更好地理解公众号文章《工程师的本体论》系列的内容。

项目按阶段组织：**phase1** 为本体引擎核心（文章 5-7），**phase2** 为 Agent 交互层（文章 8-11）。

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
└── phase2/                      # 第二阶段：OAG / Agent 交互（文章 8-11）
    ├── capability_provider.py   # Schema → Function Calling 能力清单
    ├── llm_client.py            # 双路径 LLM / mock
    ├── mock_agent.py            # 离线 mock Agent
    ├── agent_gateway.py         # 发现→调用→拒绝→重试
    ├── audit_query.py           # 决策血统审计查询
    └── run_phase2_demo.py       # 演示入口
```

---

## 🚀 快速开始

### 前置要求

- Python 3.8+
- **phase1**：无外部依赖（仅 Python 标准库）
- **phase2**：可选 `openai`（真实 LLM 路径）；未安装则自动 fallback 到 mock

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

**最后更新**：2026-06-01

如果这个 Demo 对你有帮助，欢迎 Star ⭐
