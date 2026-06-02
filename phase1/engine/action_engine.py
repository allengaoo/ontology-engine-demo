"""
ActionEngine - 操作引擎（核心协调器）

职责：
- 协调整个操作执行链路
- 管理内存事务（在内存中应用变更，全部通过后才写文件）
- 是唯一的写入入口

对应Palantir：操作服务（执行部分）

关键设计（第5篇"第一个决策"）：
1. 加载快照
2. 校验前置条件（"入场券"）
3. 在内存中应用变更（文件未动）
4. 校验全局规则（"出场检查"，检查新状态）
5. 如果任何一步失败，回滚（内存状态丢弃）
6. 全部通过，才第一次写文件

这个流程确保了：
- 规则在"写入后"执行（检查新状态）
- 原子性（要么全成功，要么什么都没改）
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
import uuid

from .schema_loader import SchemaLoader, ActionType
from .object_store import ObjectStore
from .rule_engine import RuleEngine, RuleViolation
from .audit_logger import AuditLogger


@dataclass
class ActionResult:
    """操作执行结果"""
    success: bool
    message: str
    event_id: Optional[str] = None
    violations: Optional[List[Dict[str, str]]] = None
    created_objects: Optional[Dict[str, str]] = None
    
    @classmethod
    def success_result(cls, message: str, event_id: str, created_objects: Dict = None):
        return cls(
            success=True,
            message=message,
            event_id=event_id,
            created_objects=created_objects or {}
        )
    
    @classmethod
    def rejected(cls, message: str, violations: List[Dict[str, str]] = None):
        return cls(
            success=False,
            message=message,
            violations=violations or []
        )


class ActionEngine:
    """
    操作引擎 - 唯一的写入入口
    
    重要：所有写操作都必须通过这个引擎，没有旁路
    这确保了所有写入都经过规则校验
    """
    
    def __init__(
        self,
        schema_loader: SchemaLoader,
        object_store: ObjectStore,
        rule_engine: RuleEngine,
        audit_logger: AuditLogger
    ):
        self.schema_loader = schema_loader
        self.object_store = object_store
        self.rule_engine = rule_engine
        self.audit_logger = audit_logger
    
    def execute_action(
        self,
        action_id: str,
        params: Dict[str, Any],
        caller: str = "system"
    ) -> ActionResult:
        """
        执行一个操作
        
        这是第5篇核心流程的完整实现
        """
        try:
            # 1. 加载操作定义
            action = self.schema_loader.get_action_type(action_id)
            
            # 2. 加载执行前的快照（用于审计和可能的回滚）
            snapshot_before = self.object_store.create_snapshot()
            
            # 3. 校验前置条件（"入场券"）
            precondition_result = self._check_preconditions(action, params, caller)
            if not precondition_result.success:
                # 前置条件失败，记录拒绝日志
                self.audit_logger.log_decision(
                    action_id=action_id,
                    caller=caller,
                    params=params,
                    snapshot=self._extract_relevant_snapshot(snapshot_before, params),
                    outcome='rejected',
                    rejection_reason=precondition_result.message
                )
                return precondition_result
            
            # 4. 在内存中应用变更（文件未动！）
            created_objects = self._apply_effects(action, params, caller)
            
            # 5. 校验全局规则（"出场检查"，检查变更后的新状态）
            # 这里设置 collect_all=True，收集所有违规（第6篇发现的边界）
            rules_passed, violations = self.rule_engine.evaluate_rules(
                action_id,
                params,
                collect_all=True  # 一次性告知所有问题
            )
            
            if not rules_passed:
                # 规则失败 → 回滚（恢复到操作前的快照）
                self.object_store.restore_snapshot(snapshot_before)
                
                # 构建拒绝消息
                violation_messages = [v['message'] for v in violations]
                rejection_message = '; '.join(violation_messages)
                
                # 记录拒绝日志（包含被违反的规则）
                self.audit_logger.log_decision(
                    action_id=action_id,
                    caller=caller,
                    params=params,
                    snapshot=self._extract_relevant_snapshot(snapshot_before, params),
                    outcome='rejected',
                    rejection_reason=rejection_message,
                    triggered_rule=violations[0]['rule_id'] if violations else None
                )
                
                return ActionResult.rejected(
                    message=rejection_message,
                    violations=violations
                )
            
            # 6. 全部通过 → 提交（第一次也是唯一一次写文件）
            self.object_store.persist_all()
            
            # 7. 记录成功日志（包含快照和通过的规则）
            passed_rule_ids = [r.rule_id for r in self.rule_engine.get_triggered_rules(action_id)]
            snapshot_after = self.object_store.create_snapshot()
            
            event_id = self.audit_logger.log_decision(
                action_id=action_id,
                caller=caller,
                params=params,
                snapshot=self._extract_relevant_snapshot(snapshot_after, params),
                outcome='success',
                passed_rules=passed_rule_ids
            )
            
            return ActionResult.success_result(
                message=f"操作 {action_id} 执行成功",
                event_id=event_id,
                created_objects=created_objects
            )
        
        except Exception as e:
            # 任何异常都视为失败，不写文件
            return ActionResult.rejected(
                message=f"操作执行失败: {str(e)}"
            )
    
    def _check_preconditions(
        self,
        action: ActionType,
        params: Dict[str, Any],
        caller: str
    ) -> ActionResult:
        """
        检查前置条件
        
        前置条件回答："此刻能不能执行"
        - 供应商状态是否active
        - 调用方是否有权限
        - 必需参数是否提供
        """
        for precond in action.preconditions:
            condition = precond['condition']
            message = precond['message']
            
            # 构建检查上下文
            context = self._build_precondition_context(params)
            
            try:
                # 转换表达式中的对象访问语法（supplier.status -> supplier['status']）
                condition_eval = condition
                if 'supplier.' in condition:
                    condition_eval = condition.replace('supplier.', "supplier['").replace(' ==', "'] ==")
                if 'order.' in condition:
                    condition_eval = condition.replace('order.', "order['").replace(' ==', "'] ==")
                
                # 评估前置条件表达式
                result = eval(condition_eval, {"__builtins__": {}}, context)
                if not result:
                    return ActionResult.rejected(
                        message=f"前置条件失败: {message}"
                    )
            except Exception as e:
                return ActionResult.rejected(
                    message=f"前置条件检查失败: {e}"
                )
        
        return ActionResult.success_result("前置条件通过", "")
    
    def _build_precondition_context(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """构建前置条件检查的上下文"""
        context = {}
        
        # 加载相关对象
        if 'supplier_pk' in params:
            supplier = self.object_store.get_object('Supplier', params['supplier_pk'])
            if supplier:
                context['supplier'] = supplier
        
        if 'order_pk' in params:
            order = self.object_store.get_object('PurchaseOrder', params['order_pk'])
            if order:
                context['order'] = order
        
        context.update(params)
        return context
    
    def _apply_effects(
        self,
        action: ActionType,
        params: Dict[str, Any],
        caller: str
    ) -> Dict[str, str]:
        """
        应用操作效果（仅在内存中）
        
        返回创建的对象 {type: pk}
        """
        created = {}
        
        for effect in action.effects:
            if 'create_object' in effect:
                # 创建对象
                spec = effect['create_object']
                obj_type = spec['type']
                properties = self._resolve_properties(spec['properties'], params, caller)
                
                # 生成pk
                if 'pk' not in properties:
                    properties['pk'] = f"{obj_type[:2].upper()}-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
                
                self.object_store.create_object(obj_type, properties)
                created[obj_type] = properties['pk']
            
            elif 'update_object' in effect:
                # 更新对象
                spec = effect['update_object']
                obj_type = spec['type']
                pk = self._resolve_value(spec['pk'], params, caller)
                updates = self._resolve_properties(spec['properties'], params, caller)
                
                self.object_store.update_object(obj_type, pk, updates)
        
        return created
    
    def _resolve_properties(
        self,
        properties: Dict[str, Any],
        params: Dict[str, Any],
        caller: str
    ) -> Dict[str, Any]:
        """解析属性中的占位符"""
        resolved = {}
        for key, value in properties.items():
            resolved[key] = self._resolve_value(value, params, caller)
        return resolved
    
    def _resolve_value(self, value: Any, params: Dict[str, Any], caller: str) -> Any:
        """解析单个值中的占位符"""
        if not isinstance(value, str):
            return value
        
        # 处理 {param_name} 格式的占位符
        if value.startswith('{') and value.endswith('}'):
            expr = value[1:-1]
            
            if expr == 'caller':
                return caller
            
            # 处理简单表达式（如 supplier.outstanding_amount + amount）
            if '+' in expr or '-' in expr or '*' in expr or '/' in expr:
                context = dict(params)
                
                # 加载对象，并展平属性
                if 'supplier_pk' in params:
                    supplier = self.object_store.get_object('Supplier', params['supplier_pk'])
                    if supplier:
                        # 展平对象，确保数值类型
                        for key, val in supplier.items():
                            if key in ['credit_limit', 'outstanding_amount']:
                                try:
                                    context[key] = float(val) if isinstance(val, str) else val
                                except (ValueError, TypeError):
                                    context[key] = val
                            else:
                                context[key] = val
                
                # 转换表达式中的对象访问语法 (supplier.outstanding_amount -> outstanding_amount)
                expr_eval = expr
                if 'supplier.' in expr:
                    # 替换 supplier.xxx 为 xxx（因为我们已经展平到context中）
                    expr_eval = expr.replace('supplier.', '')
                
                try:
                    result = eval(expr_eval, {"__builtins__": {}}, context)
                    # 确保结果是数值类型
                    if isinstance(result, (int, float)):
                        return result
                    return float(result) if isinstance(result, str) else result
                except Exception as e:
                    return value
            
            # 直接从params取值
            return params.get(expr, value)
        
        return value
    
    def _extract_relevant_snapshot(
        self,
        full_snapshot: Dict[str, Dict[str, Any]],
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        从完整快照中提取与本次操作相关的对象
        
        减少日志体积，只保留相关对象
        """
        relevant = {}
        
        # 提取供应商
        if 'supplier_pk' in params:
            pk = params['supplier_pk']
            if 'Supplier' in full_snapshot and pk in full_snapshot['Supplier']:
                relevant[f'Supplier/{pk}'] = full_snapshot['Supplier'][pk]
        
        # 提取认证
        if 'Certification' in full_snapshot:
            for cert_pk, cert in full_snapshot['Certification'].items():
                if cert.get('supplier_pk') == params.get('supplier_pk'):
                    relevant[f'Certification/{cert_pk}'] = cert
        
        return relevant
