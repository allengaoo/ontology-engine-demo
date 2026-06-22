"""
OntologyAgent：规则分析与方案生成Agent

职责：
  1. 读取CRITICAL + RULE + CONTEXT约束
  2. 分析规则调整的影响
  3. 生成调整方案
  4. 写入RULE层

权限：
  - 可读：CRITICAL, RULE, CONTEXT
  - 可写：RULE
"""

from .multi_agent_router import Task, AgentResult


class OntologyAgent:
    """规则分析Agent"""
    
    def __init__(self):
        self.name = "OntologyAgent"
        self.version = 1  # 方案版本号（用于重试）
    
    def execute(self, task: Task, router) -> AgentResult:
        """执行规则分析与方案生成"""
        print(f"\n[{self.name}] 开始执行任务... (方案 v{self.version})")
        
        # 读取 CRITICAL 约束（优先 manifest，回退 mock）
        critical_rules = self._get_critical_rules(task)
        print(f"  读取 CRITICAL 层：{len(critical_rules)} 条约束")
        if task.context.get("manifest_constraints"):
            print(f"    （来自 InjectManifest：{[c.get('id') for c in critical_rules[:4]]}）")
        
        # 解析IntentAgent的意图
        intent = task.context.get("intent", {})
        
        # 生成方案
        if task.feedback:
            # 重试场景：根据SimAgent反馈修正方案
            proposal = self._revise_proposal(intent, task.feedback)
        else:
            # 首次生成
            proposal = self._generate_initial_proposal(intent, critical_rules)
        
        print(f"  生成方案：{proposal}")
        
        # 写入RULE层（模拟）
        
        return AgentResult(
            status="needs_verification",
            output=proposal,
            next_agent="SimAgent"  # 建议交给SimAgent验证
        )
    
    def _get_critical_rules(self, task: Task) -> list:
        """获取 CRITICAL 约束：P1 优先读 manifest，否则 mock。"""
        constraints = (task.context or {}).get("manifest_constraints")
        if constraints:
            return [
                {
                    "id": c.get("id"),
                    "desc": c.get("desc") or c.get("title"),
                    "rule_id": c.get("rule_id"),
                    "enforcement": c.get("enforcement"),
                }
                for c in constraints
            ]
        return [
            {"id": "CR-001", "desc": "认证剩余天数 >= 30 天"},
            {"id": "CR-002", "desc": "供应商状态=active 且合同状态=valid"},
            {"id": "CR-003", "desc": "未结金额 <= 信用额度"},
            {"id": "CR-004", "desc": "单笔采购 <= 50万"},
        ]
    
    def _generate_initial_proposal(self, intent: dict, critical_rules: list) -> dict:
        """生成初始方案"""
        if intent.get("type") == "kafka_idempotency_fix":
            patterns = intent.get("pattern_ids") or []
            return {
                "proposal_id": f"v{self.version}",
                "action": "apply_idempotency_pattern",
                "target": intent.get("target_file", "procurement_service.py"),
                "measures": ["idempotency_key", "processed_events 去重表"],
                "pattern_ids": patterns,
                "constraints_honored": [c.get("id") for c in critical_rules],
                "confidence": 0.85,
            }

        # 阈值调整（023 场景）
        from_val = intent.get("from_value", 30)
        to_val = intent.get("to_value", 15)
        
        return {
            "proposal_id": f"v{self.version}",
            "action": "update_threshold",
            "target": "认证有效期阈值",
            "from_value": from_val,
            "to_value": to_val,
            "additional_measures": ["增加预警机制（45天）"],
            "confidence": 0.8
        }
    
    def _revise_proposal(self, intent: dict, feedback: str) -> dict:
        """根据反馈修正方案"""
        self.version += 1
        
        # 如果反馈说供应商不合格，则保守策略：保持原阈值
        if "不合格" in feedback or "仍" in feedback:
            return {
                "proposal_id": f"v{self.version}",
                "action": "keep_threshold_add_warning",
                "target": "认证有效期阈值",
                "from_value": 30,
                "to_value": 30,  # 保持不变
                "additional_measures": ["增加45天预警", "Beta供应商专项监控"],
                "confidence": 0.9,
                "reason": "基于SimAgent反馈修正"
            }
        
        return self._generate_initial_proposal(intent, [])
