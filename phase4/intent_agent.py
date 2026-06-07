"""
IntentAgent：意图理解Agent

职责：
  1. 解析用户自然语言意图
  2. 提取关键实体和目标
  3. 写入CONTEXT层

权限：
  - 可读：CONTEXT
  - 可写：CONTEXT
"""

from .multi_agent_router import Task, AgentResult, TaskType


class IntentAgent:
    """意图理解Agent"""
    
    def __init__(self):
        self.name = "IntentAgent"
    
    def execute(self, task: Task, router) -> AgentResult:
        """执行意图理解"""
        print(f"\n[{self.name}] 开始执行任务...")
        
        # 简化实现：关键词提取
        desc = task.description
        
        # 判断意图类型
        if "阈值" in desc and "调整" in desc:
            # 提取阈值调整意图
            intent = self._parse_threshold_adjustment(desc)
        else:
            intent = {"type": "unknown", "raw": desc}
        
        print(f"  解析结果：{intent}")
        
        # 写入CONTEXT层（模拟）
        # 真实实现应调用phase3的MemoryStore.write()
        
        return AgentResult(
            status="completed",
            output=intent,
            next_agent="OntologyAgent"  # 建议下一步交给OntologyAgent
        )
    
    def _parse_threshold_adjustment(self, desc: str) -> dict:
        """解析阈值调整意图"""
        # 简化实现：正则提取
        import re
        
        # 尝试提取数字
        numbers = re.findall(r'\d+', desc)
        
        result = {
            "type": "threshold_adjustment",
            "target": "认证有效期",
            "raw": desc
        }
        
        if len(numbers) >= 2:
            result["from_value"] = int(numbers[0])
            result["to_value"] = int(numbers[1])
        
        # 安全约束检测
        if "安全" in desc or "确保" in desc:
            result["constraint"] = "needs_safety_verification"
        
        return result
