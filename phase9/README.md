# Phase 9：Memory Prompt 流水线 + 多 EP 队列

Phase 8 闭合写侧（Promotion Gate / Session Flush / 跨 EP 可见）。
Phase 9 闭合读侧：统一 inject 拼装，并把多 EP 从脚本提升为 Harness 队列。

## 架构

```
phase9/
├── memory_prompt_builder.py   # ①Intent → ②Retrieval → ③Compression → ④Manifest
├── ep_queue.py                # 多 EP 串行：run → promote → flush → reload
├── lineage_expander.py        # derived_from 一跳扩展（044）
├── memory_ops.py              # 队列后的 health / GC dry-run（045）
├── run_phase9_demo.py         # EP-1 → EP-2 Manifest 差分验收
├── run_phase9_lineage_demo.py # DEC/PAT → derived_from 一跳验证
├── run_phase9_ops_demo.py     # 队列节奏下的记忆治理验证
└── README.md
```

| 层 | 模块 | LLM |
|----|------|-----|
| Harness | `ep_queue`（复用 phase8 Promotion / Flush / Coordinator） | 否 |
| Ontology | `MemoryPromptBuilder`（封装 IntentRouter + FederatedInjector） | 否 |
| Agent | phase8 BSA / CA（只读 Manifest） | 是 |

主链：

```
EpQueue
  → EPCoordinator.run_ep
  → MemoryPromptBuilder.build(agent_scope)
  → BSA/CA
  → PASS → PromotionGate → MemoryEPWriteback → SessionFlush → reload
  → 下一 EP
```

## 与 Phase 8 差异

| 维度 | Phase 8 | Phase 9 |
|------|---------|---------|
| inject | Coordinator 私有 `_inject_for_agent` | **MemoryPromptBuilder** 四段可审计 |
| 跨 EP | `run_cross_ep_demo` 脚本 | **EpQueue** 状态机 |
| 验收 | EP-2 能看见写回 id | + 四段命中数 / Manifest 差分 |

## 运行

```bash
cd democode
python3 phase9/run_phase9_demo.py --no-llm --dry-run
python3 phase9/run_phase9_demo.py --no-llm
python3 phase9/run_phase9_demo.py                      # 真实模型（.env，qwen3-32b）
python3 phase9/run_phase9_demo.py --workspace ./ws9    # 指定隔离目录（默认临时目录）

# 044：血统那一跳
python3 phase9/run_phase9_lineage_demo.py --no-llm

# 045：队列节奏下的记忆治理
python3 phase9/run_phase9_ops_demo.py --no-llm
```

默认写回落临时隔离目录并在结束时清理，不污染 `phase6/instances`。

真实 qwen3-32b 验收（约 70s）：EP-2 BSA 读到 EP-1 写回后规划 3 Unit，
CA 逐 Unit 出码（27/15/45 行），VerifyGate PASS 19 项，
`✓ EP-2 Manifest 可见 EP-1 晋升`；Compression 全局上限 600 裁 4 个 warm、保护 hot。

044 验收：`LineageExpander` 从 `DEC-EP-*` 的 `derived_from` 一跳补回
`PAT-001 / AD-001 / PAT-002`，已在 Manifest 中的 `CN-001 / CN-002` 只标记为
`already_present`，不重复注入。

045 验收：两个 EP 入队后，reload 后 health 快照可见；queue idle 时运行
GC dry-run，输出 code-arch decay=2 / degrade=1，并提示低置信度 hot 风险。

## 文章

043《042 管晋升，043 管注入：Memory Prompt 流水线与多 EP 编排》  
044《血统那一跳：derived_from 如何进入 Manifest》  
045《多 EP 节奏下的记忆治理》

## 复用

- phase6：`FederatedInjector` · `IntentRouter` · `BudgetConfig` · `MemoryActions`
- phase7：`AgentMemoryScope` · `manifest_parser`
- phase8：`EPCoordinator` · `EPPromotionGate` · `SessionFlush` · `MemoryEPWriteback`
