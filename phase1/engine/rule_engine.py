"""
RuleEngine - 规则引擎

职责：
- 对操作后的新状态执行全局规则校验
- 判断业务不变式是否被违反

对应Palantir：操作服务（规则部分）

关键设计（第5篇"第一个决策"）：
- 规则在写入"之后"执行，而不是之前
- 规则检查的是"执行后的状态是否合法"，不是"此刻能否执行"
- 前置条件是"入场券"，全局规则是"出场检查"
"""

from typing import Dict, Any, List, Tuple
from .schema_loader import SchemaLoader, Rule
from .object_store import ObjectStore


class RuleViolation(Exception):
    """规则违反异常"""
    def __init__(self, rule_id: str, message: str):
        self.rule_id = rule_id
        self.message = message
        super().__init__(message)


class RuleEngine:
    """规则引擎"""
    
    def __init__(self, schema_loader: SchemaLoader, object_store: ObjectStore):
        self.schema_loader = schema_loader
        self.object_store = object_store
    
    def evaluate_rules(
        self,
        action_id: str,
        params: Dict[str, Any],
        collect_all: bool = True
    ) -> Tuple[bool, List[Dict[str, str]]]:
        """
        评估操作触发的所有规则
        
        参数：
        - action_id: 操作ID
        - params: 操作参数
        - collect_all: 是否收集所有违规（True）还是遇到第一个就返回（False）
        
        返回：
        - (是否全部通过, 违规列表)
        
        注意：这个方法在"写入后"调用，检查的是内存中的新状态
        """
        rules = self.schema_loader.get_rules_for_action(action_id)
        violations = []
        
        for rule in rules:
            try:
                self._evaluate_single_rule(rule, params)
            except RuleViolation as e:
                violations.append({
                    "rule_id": e.rule_id,
                    "message": e.message
                })
                
                # 如果不收集全部，遇到第一个违规就返回
                if not collect_all:
                    return False, violations
        
        return len(violations) == 0, violations
    
    def _evaluate_single_rule(self, rule: Rule, params: Dict[str, Any]):
        """
        评估单条规则
        
        这里使用了简化的表达式评估（eval）
        生产环境应该使用更安全的DSL或规则引擎
        """
        # 构建评估上下文
        context = self._build_evaluation_context(rule, params)
        
        try:
            # 评估规则表达式
            # 警告：这里使用 eval() 仅用于Demo，生产环境需要使用安全的规则引擎
            result = eval(rule.expression, {"__builtins__": {}}, context)
            
            if not result:
                raise RuleViolation(rule.rule_id, rule.violation_message)
        
        except NameError as e:
            # 表达式引用了不存在的变量
            raise RuleViolation(
                rule.rule_id,
                f"规则表达式错误：{e}"
            )
        except Exception as e:
            # 其他错误
            raise RuleViolation(
                rule.rule_id,
                f"规则评估失败：{e}"
            )
    
    def _build_evaluation_context(
        self,
        rule: Rule,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        构建规则评估的上下文
        
        从ObjectStore加载规则需要的对象，展平到上下文中
        例如：supplier.credit_limit 变成 credit_limit
        """
        context = {}
        
        # 加载规则需要的对象
        for req in rule.requires_objects:
            obj_type = req['type']
            filter_expr = req.get('filter', '')
            
            # 简化：直接从params获取pk
            # 实际应该解析filter表达式
            if obj_type == 'Supplier':
                pk = params.get('supplier_pk')
                if pk:
                    obj = self.object_store.get_object(obj_type, pk)
                    if obj:
                        # 展平对象属性到上下文（确保数值类型）
                        for key, value in obj.items():
                            # 尝试转换为数值
                            if key in ['credit_limit', 'outstanding_amount', 'amount']:
                                try:
                                    context[key] = float(value) if isinstance(value, str) else value
                                except (ValueError, TypeError):
                                    context[key] = value
                            else:
                                context[key] = value
            
            elif obj_type == 'Certification':
                # 查询供应商的认证证书
                supplier_pk = params.get('supplier_pk')
                if supplier_pk:
                    certs = self.object_store.query_objects(
                        'Certification',
                        lambda c: c.get('supplier_pk') == supplier_pk
                    )
                    if certs:
                        # 取最新的认证（简化）
                        cert = certs[0]
                        days_remaining = cert.get('days_remaining', 0)
                        context['cert_days_remaining'] = int(days_remaining) if isinstance(days_remaining, str) else days_remaining
            
            elif obj_type == 'PurchaseOrder':
                # 如果是订单相关的规则
                if 'amount' in params:
                    amount = params['amount']
                    context['amount'] = float(amount) if isinstance(amount, str) else amount
        
        # 添加params到上下文（确保数值类型）
        for key, value in params.items():
            if key in ['amount', 'quantity', 'credit_limit', 'outstanding_amount']:
                try:
                    context[key] = float(value) if isinstance(value, str) else value
                except (ValueError, TypeError):
                    context[key] = value
            else:
                context[key] = value
        
        return context
    
    def get_triggered_rules(self, action_id: str) -> List[Rule]:
        """获取某个操作会触发的规则列表"""
        return self.schema_loader.get_rules_for_action(action_id)
