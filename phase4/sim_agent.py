"""
SimAgent：约束模拟验证Agent

职责：
  1. 读取CRITICAL + RULE约束
  2. 模拟执行OntologyAgent的方案
  3. 验证是否违反约束
  4. 写入验证结果到CONTEXT层

权限：
  - 可读：CRITICAL, RULE
  - 可写：CONTEXT（仅验证结果）
"""

from .multi_agent_router import Task, AgentResult


class SimAgent:
    """模拟验证Agent"""
    
    def __init__(self):
        self.name = "SimAgent"
    
    def execute(self, task: Task, router) -> AgentResult:
        """执行约束模拟验证"""
        print(f"\n[{self.name}] 开始执行任务...")
        
        # 读取方案
        proposal = task.context.get("proposal", {})
        print(f"  待验证方案：{proposal.get('proposal_id')}")
        
        # 模拟当前供应商状态
        suppliers = self._get_current_suppliers()
        print(f"  当前供应商：{len(suppliers)} 家")
        
        # 模拟验证
        validation_result = self._simulate_constraint(proposal, suppliers, task)
        
        if validation_result["passed"]:
            print(f"  ✓ 验证通过")
            return AgentResult(
                status="completed",
                output=validation_result
            )
        else:
            print(f"  ✗ 验证失败：{validation_result['reason']}")
            return AgentResult(
                status="rejected",
                output=validation_result,
                reason=validation_result["reason"]
            )
    
    def _get_current_suppliers(self) -> list:
        """获取当前供应商状态（模拟数据）"""
        return [
            {
                "id": "S-ALPHA-001",
                "name": "Alpha供应商",
                "cert_remaining_days": 45,
                "status": "active"
            },
            {
                "id": "S-BETA-002",
                "name": "Beta供应商",
                "cert_remaining_days": 13,  # 剩余13天
                "status": "active"
            },
            {
                "id": "S-GAMMA-003",
                "name": "Gamma供应商",
                "cert_remaining_days": 60,
                "status": "active"
            },
        ]
    
    def _simulate_constraint(self, proposal: dict, suppliers: list, task: Task) -> dict:
        """模拟约束验证"""
        action = proposal.get("action")
        
        if action == "update_threshold":
            # 阈值调整场景
            new_threshold = proposal.get("to_value", 30)

            # manifest 中的 BIZ-CN-001 等约束作为审计参考
            manifest_cn = (task.context or {}).get("manifest_constraints", [])
            if manifest_cn:
                print(f"  manifest 约束参与验证：{[c.get('id') for c in manifest_cn]}")
            
            # 检查所有供应商是否满足新阈值
            violated_suppliers = []
            for s in suppliers:
                if s["cert_remaining_days"] < new_threshold:
                    violated_suppliers.append(s)
            
            if violated_suppliers:
                return {
                    "passed": False,
                    "reason": f"{violated_suppliers[0]['name']}剩余{violated_suppliers[0]['cert_remaining_days']}天 < {new_threshold}天，仍不合格",
                    "violated_suppliers": [s["name"] for s in violated_suppliers]
                }
        
        elif action == "apply_idempotency_pattern":
            # Kafka 幂等修复：不改变供应商认证阈值，合规约束仍满足
            constraints = (task.context or {}).get("manifest_constraints", [])
            cert_rules = [c for c in constraints if "cert" in str(c.get("rule_id", "")).lower()
                          or "认证" in str(c.get("desc", ""))]
            return {
                "passed": True,
                "reason": "幂等方案不降低认证阈值，"
                          + (f"manifest 约束 {cert_rules[0]['id']} 仍有效" if cert_rules else "无阈值变更"),
            }

        elif action == "keep_threshold_add_warning":
            # 保持阈值+增加预警，无风险
            return {
                "passed": True,
                "reason": "保持30天阈值，所有供应商满足要求"
            }
        
        # 默认通过
        return {"passed": True, "reason": "无约束违反"}
