#!/usr/bin/env python3
"""
Phase 4 完整演示：三Agent协作

场景：认证阈值调整（30天 → 15天，确保安全）

执行流程：
  Step 1: IntentAgent 解析意图
  Step 2: OntologyAgent 生成方案v1（阈值改15天）
  Step 3: SimAgent 验证 → 拒绝（Beta供应商13天 < 15天）
  Step 4: OntologyAgent 修正方案v2（保持30天+预警）
  Step 5: SimAgent 重新验证 → 通过
  Step 6: 呈报用户

关键观察点：
  - 制衡机制在Step 3生效（SimAgent否决OntologyAgent）
  - 共享记忆作为通信介质（CONTEXT/RULE层）
  - 权限隔离（每个Agent只读写自己权限范围）
"""

import sys
import os
from pathlib import Path

# 添加democode到path
DEMOCODE_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(DEMOCODE_ROOT))

from phase4.multi_agent_router import MultiAgentRouter, Task, TaskType
from phase4.intent_agent import IntentAgent
from phase4.ontology_agent import OntologyAgent
from phase4.sim_agent import SimAgent
from phase4.agent_coordinator import DAGExecutor


def run_phase4_demo():
    """Phase 4 完整演示"""
    
    # 初始化
    memory_dir = DEMOCODE_ROOT / "memory"
    router = MultiAgentRouter(memory_dir=str(memory_dir))
    
    # 注册三个Agent
    router.register_agent("IntentAgent", IntentAgent())
    router.register_agent("OntologyAgent", OntologyAgent())
    router.register_agent("SimAgent", SimAgent())
    
    # 创建DAG执行器
    executor = DAGExecutor(router)
    
    # 用户输入
    task = Task(
        description="把认证有效期阈值从30天调整为15天，但要确保安全",
        user_id="user-001",
        type=TaskType.UNKNOWN
    )
    
    # 执行DAG
    result = executor.execute(task)
    
    # 打印结果
    print(f"\n{'=' * 60}")
    print(f"  执行结果")
    print(f"{'=' * 60}")
    
    print(f"\n状态：{result['status']}")
    print(f"总步数：{len(result['steps'])}")
    print(f"重试次数：{result.get('retry_count', 0)}")
    
    if result['status'] == 'success':
        print(f"\n最终方案：")
        proposal = result['final_proposal']
        print(f"  方案ID：{proposal['proposal_id']}")
        print(f"  操作：{proposal['action']}")
        print(f"  阈值：{proposal['from_value']} → {proposal['to_value']} 天")
        print(f"  额外措施：{', '.join(proposal.get('additional_measures', []))}")
        print(f"  置信度：{proposal.get('confidence', 0)}")
    
    # 打印执行路径
    print(f"\n执行路径：")
    for step in result['steps']:
        status_icon = "✓" if step['status'] in ['completed', 'needs_verification'] else "✗"
        print(f"  {status_icon} Step {step['id']}: {step['agent']} → {step['status']}")
        if step.get('reason'):
            print(f"      └─ 原因：{step['reason']}")
    
    print(f"\n{'=' * 60}")
    print("  关键观察")
    print(f"{'=' * 60}")
    print("1. 制衡机制：SimAgent在Step 3拒绝了OntologyAgent的方案v1")
    print("2. 反馈循环：OntologyAgent根据拒绝原因修正为方案v2")
    print("3. 权限隔离：各Agent只读写自己权限范围内的记忆层")
    print("4. 可追溯性：完整记录了决策路径和每一步的理由")
    
    return result


def print_architecture():
    """打印Multi-Agent架构"""
    print(f"\n{'=' * 60}")
    print("  Multi-Agent 架构")
    print(f"{'=' * 60}")
    print("""
┌─────────────┐
│ Router      │  任务路由 + 权限校验
└──────┬──────┘
       │
       ├──→ IntentAgent     [读写：CONTEXT]
       │    解析意图、结构化目标
       │
       ├──→ OntologyAgent   [读：C+R+CTX / 写：RULE]
       │    规则分析、方案生成
       │
       └──→ SimAgent        [读：C+R / 写：CTX]
            约束模拟、安全验证

执行流程（DAG）：
  IntentAgent → OntologyAgent → SimAgent
                     ↑________________↓
                    （拒绝时重试）
""")


if __name__ == "__main__":
    print_architecture()
    result = run_phase4_demo()
    
    print(f"\n✓ Phase 4 演示完成")
