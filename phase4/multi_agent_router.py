"""
Multi-Agent Router：任务路由与权限校验

功能：
  1. 能力注册：每个Agent声明自己的能力
  2. 任务路由：根据任务特征匹配最合适的Agent
  3. 权限校验：确保Agent只读写自己权限范围内的记忆层
  4. 后台任务模式（BackgroundTaskStore）：
     子 Agent 结果不立即返回，而是存入任务仓库，
     主 Agent 下一轮通过 system_reminder 拉取——
     防止中间结果进入可被压缩的消息流（参考 AgentScope background task 设计）。
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
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


# ── 后台任务仓库 ─────────────────────────────────────────────────────────────

@dataclass
class BackgroundTask:
    """后台任务记录"""
    task_id: str
    agent_name: str
    description: str
    status: str = "running"   # running / completed / failed
    result: Optional[AgentResult] = None
    system_reminder: Optional[str] = None  # 注入下一轮 system prompt 的摘要


class BackgroundTaskStore:
    """
    后台任务仓库（对应 AgentScope background task + system-reminder 机制）

    设计原则：
      - 子 Agent 的结果不直接注入当前消息流（防止被压缩/丢失）
      - 结果存入仓库，主 Agent 在下一轮 call() 开始时通过
        pop_pending_reminders() 拉取，作为 system_reminder 注入
      - task_id 由调用方持有，可异步查询状态

    使用方式：
      1. 委派时：task_id = store.submit(agent_name, description)
      2. 执行后：store.complete(task_id, result)
      3. 主 Agent 下一轮：reminders = store.pop_pending_reminders()
         → 注入到 system prompt，告知"哪个子任务已完成，结果是什么"
    """

    def __init__(self):
        self._tasks: Dict[str, BackgroundTask] = {}

    def submit(self, agent_name: str, description: str) -> str:
        """提交后台任务，返回 task_id"""
        task_id = f"bg-{uuid.uuid4().hex[:8]}"
        self._tasks[task_id] = BackgroundTask(
            task_id=task_id,
            agent_name=agent_name,
            description=description,
            status="running",
        )
        return task_id

    def complete(self, task_id: str, result: AgentResult) -> None:
        """标记任务完成，生成 system_reminder"""
        if task_id not in self._tasks:
            return
        task = self._tasks[task_id]
        task.status = "completed"
        task.result = result
        # 生成主 Agent 下一轮会看到的 system reminder
        status_label = "✓ 通过" if result.status == "completed" else f"✗ {result.status}"
        task.system_reminder = (
            f"[后台任务完成] task_id={task_id} agent={task.agent_name} "
            f"状态={status_label} 摘要={str(result.output)[:200]}"
        )

    def pop_pending_reminders(self) -> List[str]:
        """
        取出所有已完成但未推送的 reminders，推送后清除。
        主 Agent 在每轮 call() 开始时调用，将结果注入 system prompt。
        """
        reminders = []
        for task in list(self._tasks.values()):
            if task.status == "completed" and task.system_reminder:
                reminders.append(task.system_reminder)
                task.system_reminder = None  # 已推送，清除
        return reminders

    def get_status(self, task_id: str) -> Optional[str]:
        """查询任务状态"""
        task = self._tasks.get(task_id)
        return task.status if task else None


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
        "IntentAgent":   {"read": ["context"],                   "write": ["context"]},
        "OntologyAgent": {"read": ["critical", "rule", "context"], "write": ["rule"]},
        "SimAgent":      {"read": ["critical", "rule"],           "write": ["context"]},
    }

    # 上下文切片配置：每个 Agent 只注入它本轮需要的记忆层
    # （对应 AgentScope ISOLATED workspace 的上下文隔离）
    AGENT_CONTEXT_LAYERS: Dict[str, List[str]] = {
        "IntentAgent":   ["context"],
        "OntologyAgent": ["critical", "rule", "context"],
        "SimAgent":      ["critical", "rule"],
    }

    def __init__(self, memory_dir: str):
        self.memory_dir = memory_dir
        self._agents: Dict[str, Any] = {}
        self.bg_tasks = BackgroundTaskStore()  # 后台任务仓库

    def register_agent(self, name: str, agent: Any) -> None:
        """注册Agent实例"""
        self._agents[name] = agent
        print(f"✓ 注册Agent：{name}")

    def route_task(self, task: Task) -> str:
        """路由任务到最合适的Agent"""
        if task.type == TaskType.INTENT_UNDERSTANDING:
            return "IntentAgent"
        elif task.type == TaskType.RULE_MODIFICATION:
            return "OntologyAgent"
        elif task.type == TaskType.SAFETY_VERIFICATION:
            return "SimAgent"

        desc = task.description.lower()
        if any(kw in desc for kw in ["想做", "目标", "讨论", "想"]):
            return "IntentAgent"
        elif any(kw in desc for kw in ["规则", "调整", "修改", "阈值"]):
            return "OntologyAgent"
        elif any(kw in desc for kw in ["验证", "模拟", "安全", "检查"]):
            return "SimAgent"

        return "IntentAgent"

    def check_permission(self, agent_name: str, operation: str, layer: str) -> bool:
        """检查Agent权限"""
        permissions = self.AGENT_PERMISSIONS.get(agent_name, {})
        allowed_layers = permissions.get(operation, [])
        return layer in allowed_layers

    def build_agent_context(self, agent_name: str, task: Task) -> Dict[str, Any]:
        """
        构建 Agent 的上下文切片（Context Slice）

        每个 Agent 只看到本轮需要的信息，不接触全量任务上下文：
          IntentAgent   → 用户原始输入 + CONTEXT 层记忆
          OntologyAgent → 结构化意图 + CRITICAL/RULE/CONTEXT 层
          SimAgent      → 调整方案 + CRITICAL/RULE 层

        这实现了文章 019 描述的"上下文切片"设计。
        """
        allowed_layers = self.AGENT_CONTEXT_LAYERS.get(agent_name, [])
        sliced: Dict[str, Any] = {}

        # 用户原始输入：所有 Agent 都需要
        sliced["description"] = task.description

        # 意图结果：仅 OntologyAgent/SimAgent 需要
        if "intent" in task.context and agent_name in ("OntologyAgent", "SimAgent"):
            sliced["intent"] = task.context["intent"]

        # 方案：仅 SimAgent 需要
        if "proposal" in task.context and agent_name == "SimAgent":
            sliced["proposal"] = task.context["proposal"]

        # 反馈：OntologyAgent 重试时需要
        if task.feedback and agent_name == "OntologyAgent":
            sliced["feedback"] = task.feedback

        sliced["allowed_layers"] = allowed_layers
        return sliced

    def execute_agent(self, agent_name: str, task: Task) -> AgentResult:
        """执行Agent（带权限校验 + 上下文切片）"""
        if agent_name not in self._agents:
            raise ValueError(f"未注册Agent：{agent_name}")

        agent = self._agents[agent_name]
        # 注入上下文切片，Agent 只看到自己需要的部分
        task.context["_slice"] = self.build_agent_context(agent_name, task)
        result = agent.execute(task, self)
        return result

    def execute_agent_background(self, agent_name: str, task: Task) -> str:
        """
        后台委派模式：立即返回 task_id，Agent 异步执行，
        结果通过 BackgroundTaskStore 在主 Agent 下一轮注入。

        适用场景：
          - 不需要立即等待结果的子任务
          - 并行处理多个独立任务时避免阻塞主 Agent
          - 防止子 Agent 中间产物进入可被压缩的消息流

        使用方式：
          task_id = router.execute_agent_background("SimAgent", task)
          # ... 主 Agent 继续其他工作 ...
          reminders = router.bg_tasks.pop_pending_reminders()
          # → 下一轮将 reminders 注入 system prompt
        """
        task_id = self.bg_tasks.submit(agent_name, task.description)
        # 当前实现为同步执行后标记完成（演示用）
        # 生产环境可替换为 threading.Thread 或 asyncio
        result = self.execute_agent(agent_name, task)
        self.bg_tasks.complete(task_id, result)
        return task_id
