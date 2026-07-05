# Phase 8：Harness + 本体 + 双 Agent

半闭域端侧业务编码：Harness 管循环，Ontology 管执法，**两个 LLM 节点**（BSA + CA）。

## 架构

| 层 | 模块 | LLM |
|----|------|-----|
| Harness | `ep_coordinator` · `verify_gate` · `atomicity_check` · `dag_state` | 否 |
| Ontology | phase6 `FederatedInjector` + phase7 `MemoryWriteback` | 否 |
| Agent | `BusinessStructureAgent` (BSA) · `CodingAgent` (CA) | 是 |

主循环：**锚定 → inject(BSA) → Plan → AtomicityCheck → inject(CA)×Unit → VerifyGate → writeback**

VerifyGate 三路：`PASS` / `FAIL_IMPL`（→ CA retry）/ `FAIL_STRUCT`（→ BSA replan）

## 运行

```bash
cd democode
python3 phase8/run_phase8_demo.py --dry-run
python3 phase8/run_phase8_demo.py --scenario kafka_idempotent --dry-run
python3 phase8/run_phase8_demo.py --scenario impl_fail --dry-run
python3 phase8/run_phase8_demo.py --scenario struct_fail --dry-run
python3 phase8/run_phase8_demo.py --reload-roles --dry-run
```

## 与 Phase 7 差异

| 维度 | Phase 7 | Phase 8 |
|------|---------|---------|
| LLM Agent | 4（Intent/Ontology/Sim/Coder） | **2（BSA/CA）** |
| 验证 | SimAgent（LLM） | **VerifyGate（确定性）** |
| 规划输出 | proposal | **StructurePlan + Unit** |
| 执行 | 整任务一次 | **按 Unit fresh context** |

## 状态

### P0 ✅

- EP 状态机 + VerifyGate 三路 + AtomicityCheck
- BSA / CA + **真实 LLM 路径**（`llm_chat.py`，无 key 时 stub）
- `--no-llm` 强制离线演示
- DagState checkpoint + `--resume`

### P1 待做

- StructurePlan 正式 writeback 到 Ontology
- MMS 编排合并注释

## LLM 配置

```bash
cp .env.example .env
# LLM_API_KEY=...
# LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1  # 可选
# LLM_MODEL=qwen3.7-plus  # 可选
pip install openai python-dotenv  # 可选
```

Phase 7：`python3 phase7/run_multi_agent_memory_demo.py --full --dry-run`  
Phase 8：`python3 phase8/run_phase8_demo.py --dry-run`

**不调 LLM 的模块**：IntentRouter、VerifyGate、AtomicityCheck、SimAgent（确定性模拟）。

## 文章

041《半闭域业务编码：Harness、本体与两个 Agent 怎么协同》
