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
- BSA / CA stub + `--dry-run` 三场景
- DagState checkpoint + `--resume` 接口
- `roles/bsa.toml` · `roles/ca.toml`

### P1 待做

- StructurePlan 正式 writeback 到 Ontology
- 真实 LLM 路径（BSA / CA）
- MMS 编排合并注释

## 文章

041《半闭域业务编码：Harness、本体与两个 Agent 怎么协同》
