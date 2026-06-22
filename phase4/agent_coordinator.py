"""
Agent Coordinator：DAG执行器 + 冲突检测 + 计划持久化

功能：
  1. 构建Agent依赖关系（DAG）
  2. 拓扑排序生成执行顺序
  3. 循环检测与终止
  4. 写冲突检测与解决
  5. Plan Mode：执行前生成可读计划摘要，意图与执行物理解耦
     （参考 AgentScope Plan Mode，计划持久化到 workspace/plans/）
"""

from pathlib import Path
from typing import Dict, List, Optional
from .multi_agent_router import Task, TaskType


class AgentCoordinator:
    """Agent协调器"""
    
    # Agent依赖关系
    AGENT_DEPENDENCIES = {
        "IntentAgent": [],
        "OntologyAgent": ["IntentAgent"],
        "SimAgent": ["OntologyAgent"],
        "CoderAgent": ["SimAgent"],
    }
    
    def __init__(self, router):
        self.router = router
    
    def build_execution_order(self) -> List[str]:
        """构建执行顺序（拓扑排序）"""
        order = []
        visited = set()
        
        def dfs(agent: str):
            if agent in visited:
                return
            visited.add(agent)
            for dep in self.AGENT_DEPENDENCIES.get(agent, []):
                dfs(dep)
            order.append(agent)
        
        for agent in self.AGENT_DEPENDENCIES:
            dfs(agent)
        
        return order


class DAGExecutor:
    """DAG执行器（含 Plan Mode）"""

    MAX_RETRY = 3  # 最大重试次数

    def __init__(self, router, plan_dir: Optional[Path] = None):
        self.router = router
        self.coordinator = AgentCoordinator(router)
        # 计划文件目录（Plan Mode）；不指定则不写磁盘
        self.plan_dir = Path(plan_dir) if plan_dir else None
        if self.plan_dir:
            self.plan_dir.mkdir(parents=True, exist_ok=True)

    def plan(self, task: Task) -> str:
        """
        Plan Mode：只读规划阶段，不执行任何状态变更。

        输出执行计划摘要（纯文本），可：
          1. 展示给用户确认
          2. 持久化到 plan_dir/plan-<task_id>.md
          3. 作为 execute() 的前置步骤

        这实现了文章 021 描述的"意图与执行物理解耦"设计：
        计划在磁盘上可查看、可修改，执行前有显式确认窗口。
        """
        import uuid
        from datetime import datetime
        plan_id = f"plan-{uuid.uuid4().hex[:6]}"
        lines = [
            f"# 执行计划 {plan_id}",
            f"创建时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"",
            f"## 任务描述",
            f"{task.description}",
            f"",
            f"## 执行步骤（DAG 拓扑顺序）",
        ]
        order = self.coordinator.build_execution_order()
        for i, agent in enumerate(order, 1):
            deps = self.coordinator.AGENT_DEPENDENCIES.get(agent, [])
            dep_str = f"（依赖：{', '.join(deps)}）" if deps else "（无依赖）"
            lines.append(f"  Step {i}. {agent} {dep_str}")
        lines += [
            f"",
            f"## 记忆层权限",
            f"  IntentAgent   → 读写 CONTEXT",
            f"  OntologyAgent → 读 CRITICAL/RULE/CONTEXT，写 RULE",
            f"  SimAgent      → 读 CRITICAL/RULE，写 CONTEXT（验证结果）",
            f"",
            f"## 终止条件",
            f"  成功：SimAgent 验证通过",
            f"  失败：OntologyAgent 重试超过 {self.MAX_RETRY} 次",
        ]
        plan_text = "\n".join(lines)

        # 持久化到磁盘（若配置了 plan_dir）
        if self.plan_dir:
            plan_path = self.plan_dir / f"{plan_id}.md"
            plan_path.write_text(plan_text, encoding="utf-8")
            print(f"  [Plan Mode] 计划已写入：{plan_path}")

        return plan_text

    def execute(self, task: Task) -> dict:
        """执行DAG流程"""
        retry_count = 0
        path = []  # 记录执行路径
        steps = []  # 记录每一步详情
        
        print(f"\n{'=' * 60}")
        print(f"  三Agent协作演示：{task.description[:30]}...")
        print(f"{'=' * 60}")
        
        # Step 1: IntentAgent（固定）
        result_intent = self._execute_step(
            agent_name="IntentAgent",
            task=task,
            path=path,
            steps=steps
        )
        task.context["intent"] = result_intent.output
        
        # Step 2: OntologyAgent（首次）
        result_ontology = self._execute_step(
            agent_name="OntologyAgent",
            task=task,
            path=path,
            steps=steps
        )
        task.context["proposal"] = result_ontology.output
        
        # Step 3-N: SimAgent验证 + 可能的OntologyAgent重试
        while retry_count < self.MAX_RETRY:
            # SimAgent验证
            result_sim = self._execute_step(
                agent_name="SimAgent",
                task=task,
                path=path,
                steps=steps
            )
            
            if result_sim.status == "completed":
                # 验证通过
                print(f"\n✓ DAG执行完成（总步数：{len(steps)}）")
                return {
                    "status": "success",
                    "steps": steps,
                    "final_proposal": task.context["proposal"],
                    "retry_count": retry_count
                }
            
            elif result_sim.status == "rejected":
                # 验证失败，返回OntologyAgent重试
                retry_count += 1
                if retry_count >= self.MAX_RETRY:
                    print(f"\n✗ 重试次数超限（{retry_count}次）")
                    return {
                        "status": "failed",
                        "steps": steps,
                        "reason": "重试次数超限"
                    }
                
                print(f"\n  → SimAgent拒绝，返回OntologyAgent修正（重试 {retry_count}/{self.MAX_RETRY}）")
                task.feedback = result_sim.reason
                
                # OntologyAgent重新生成
                result_ontology = self._execute_step(
                    agent_name="OntologyAgent",
                    task=task,
                    path=path,
                    steps=steps
                )
                task.context["proposal"] = result_ontology.output
        
        return {
            "status": "failed",
            "steps": steps,
            "reason": "未知错误"
        }
    
    def _execute_step(self, agent_name: str, task: Task, path: list, steps: list):
        """执行单个Agent步骤"""
        step_id = len(steps) + 1
        print(f"\n[Step {step_id}] {agent_name}")
        
        path.append(agent_name)
        
        # 循环检测
        if path.count(agent_name) > 3:
            raise RuntimeError(f"检测到循环：{' → '.join(path)}")
        
        # 执行Agent
        result = self.router.execute_agent(agent_name, task)
        
        # 记录步骤
        steps.append({
            "id": step_id,
            "agent": agent_name,
            "status": result.status,
            "output": result.output,
            "reason": result.reason
        })
        
        return result
