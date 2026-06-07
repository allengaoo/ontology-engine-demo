"""
Phase 4 包初始化

Multi-Agent 架构：
  Router（multi_agent_router.py）       — 任务路由 + 权限校验
  IntentAgent（intent_agent.py）        — 意图理解
  OntologyAgent（ontology_agent.py）    — 规则分析与方案生成
  SimAgent（sim_agent.py）              — 约束模拟验证
  
协调器（agent_coordinator.py）          — DAG执行 + 冲突检测

入口：run_phase4_demo.py（完整8步流程演示）
"""

from .multi_agent_router import MultiAgentRouter, Task, AgentResult
from .intent_agent import IntentAgent
from .ontology_agent import OntologyAgent
from .sim_agent import SimAgent
from .agent_coordinator import AgentCoordinator, DAGExecutor

__all__ = [
    "MultiAgentRouter", "Task", "AgentResult",
    "IntentAgent",
    "OntologyAgent",
    "SimAgent",
    "AgentCoordinator", "DAGExecutor",
]
