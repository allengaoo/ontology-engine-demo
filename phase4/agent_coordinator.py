"""
Agent Coordinator：DAG执行器 + 冲突检测

功能：
  1. 构建Agent依赖关系（DAG）
  2. 拓扑排序生成执行顺序
  3. 循环检测与终止
  4. 写冲突检测与解决
"""

from typing import Dict, List
from .multi_agent_router import Task, TaskType


class AgentCoordinator:
    """Agent协调器"""
    
    # Agent依赖关系
    AGENT_DEPENDENCIES = {
        "IntentAgent": [],
        "OntologyAgent": ["IntentAgent"],
        "SimAgent": ["OntologyAgent"],
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
    """DAG执行器"""
    
    MAX_RETRY = 3  # 最大重试次数
    
    def __init__(self, router):
        self.router = router
        self.coordinator = AgentCoordinator(router)
    
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
