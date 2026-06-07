"""
Multi-Agent Router：任务路由与权限校验

功能：
  1. 能力注册：每个Agent声明自己的能力
  2. 任务路由：根据任务特征匹配最合适的Agent
  3. 权限校验：确保Agent只读写自己权限范围内的记忆层
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from enum import Enum


class TaskType(str, Enum):
    """任务类型枚举"""
    INTENT_UNDERSTANDING = "intent_understanding"
    RULE_MODIFICATION = "rule_modification"
    SAFETY_VERIFICATION = "safety_verification"
    UNKNOWN = "unknown"


@dataclass
class Task:
    """任务定义"""
    description: str
    user_id: str
    type: TaskType = TaskType.UNKNOWN
    context: Dict[str, Any] = None
    feedback: Optional[str] = None  # 用于携带反馈重试
    
    def __post_init__(self):
        if self.context is None:
            self.context = {}


@dataclass
class AgentResult:
    """Agent执行结果"""
    status: str  # "completed" / "needs_input" / "needs_verification" / "rejected"
    output: Any
    next_agent: Optional[str] = None  # Agent建议下一步给谁
    reason: Optional[str] = None  # 拒绝原因（status=rejected时）


class MultiAgentRouter:
    """多Agent路由器"""
    
    # 能力注册表
    AGENT_CAPABILITIES = {
        "IntentAgent": [
            "intent_parse",
            "clarify_ambiguity",
            "context_summarize",
        ],
        "OntologyAgent": [
            "rule_analysis",
            "schema_modification",
            "impact_assessment",
        ],
        "SimAgent": [
            "constraint_simulation",
            "state_verification",
            "risk_evaluation",
        ],
    }
    
    # 权限矩阵
    AGENT_PERMISSIONS = {
        "IntentAgent": {"read": ["context"], "write": ["context"]},
        "OntologyAgent": {"read": ["critical", "rule", "context"], "write": ["rule"]},
        "SimAgent": {"read": ["critical", "rule"], "write": ["context"]},
    }
    
    def __init__(self, memory_dir: str):
        self.memory_dir = memory_dir
        self._agents = {}  # 注册的Agent实例
    
    def register_agent(self, name: str, agent: Any):
        """注册Agent实例"""
        self._agents[name] = agent
        print(f"✓ 注册Agent：{name}")
    
    def route_task(self, task: Task) -> str:
        """路由任务到最合适的Agent"""
        # 任务类型判断
        if task.type == TaskType.INTENT_UNDERSTANDING:
            return "IntentAgent"
        elif task.type == TaskType.RULE_MODIFICATION:
            return "OntologyAgent"
        elif task.type == TaskType.SAFETY_VERIFICATION:
            return "SimAgent"
        
        # 关键词匹配
        desc = task.description.lower()
        if any(kw in desc for kw in ["想做", "目标", "讨论", "想"]):
            return "IntentAgent"
        elif any(kw in desc for kw in ["规则", "调整", "修改", "阈值"]):
            return "OntologyAgent"
        elif any(kw in desc for kw in ["验证", "模拟", "安全", "检查"]):
            return "SimAgent"
        
        # 默认：先理解意图
        return "IntentAgent"
    
    def check_permission(
        self,
        agent_name: str,
        operation: str,  # "read" or "write"
        layer: str
    ) -> bool:
        """检查Agent权限"""
        permissions = self.AGENT_PERMISSIONS.get(agent_name, {})
        allowed_layers = permissions.get(operation, [])
        return layer in allowed_layers
    
    def execute_agent(self, agent_name: str, task: Task) -> AgentResult:
        """执行Agent（带权限校验）"""
        if agent_name not in self._agents:
            raise ValueError(f"未注册Agent：{agent_name}")
        
        agent = self._agents[agent_name]
        
        # 执行Agent任务
        result = agent.execute(task, self)
        
        return result
