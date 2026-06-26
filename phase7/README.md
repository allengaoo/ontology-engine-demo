# Phase 7：记忆感知多智能体

多智能体层（有向无环图编排）× 记忆层（联邦注入）接线。

## 模块

| 文件 | 职责 |
|------|------|
| `agent_memory_scope.py` | 智能体 × 语义域 × 层级 × 读写权限 |
| `memory_aware_coordinator.py` | 编排 + 注入 + 执行 + 写回 + 计划模式 |
| `memory_aware_agents.py` | 注入清单适配器 + 清单解析挂载 |
| `manifest_parser.py` | 注入清单 → 约束记忆 / 模式记忆 |
| `memory_writeback.py` | 决策记录写回 |
| `coder_agent.py` | 代码占位实现 + 约束校验 |
| `run_multi_agent_memory_demo.py` | 演示入口 |

## 运行

```bash
cd democode
python3 phase7/run_multi_agent_memory_demo.py                         # 仅注入清单
python3 phase7/run_multi_agent_memory_demo.py --with-agents           # P0：三智能体 + 写回
python3 phase7/run_multi_agent_memory_demo.py --with-agents --dry-run
python3 phase7/run_multi_agent_memory_demo.py --plan                  # 计划模式
python3 phase7/run_multi_agent_memory_demo.py --full --dry-run        # P1 完整有向无环图
python3 phase7/run_multi_agent_memory_demo.py --full --scenario threshold --dry-run  # 023 制衡重跑
```

## 状态

### P0 ✅

- 每智能体独立注入清单
- 注入清单 → `Agent.execute()`（挂载到 `task.context`）
- `MemoryWriteback` → 决策记录

### P1 ✅

- 本体 / 模拟验证智能体读注入清单约束（`manifest_parser.py`）
- 计划模式含各智能体权限范围 + 注入清单预览
- 代码生成智能体 + 约束记忆校验纳入有向无环图
- 模拟验证否决 → 排队写回反馈 → 本体重试（唤醒语义）
- `--scenario threshold` 完整重跑 023 制衡

### P2 待做

- AgentMemoryScope 外置配置文件
- BackgroundTaskStore 真异步

## 文章

037《多智能体的记忆接线：同一任务，每个角色看到的不一样》
