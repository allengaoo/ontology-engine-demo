"""
Intent Compiler：意图编译器

功能：
  1. 自然语言 → 结构化操作（非确定性编译）
  2. 歧义检测与延迟绑定
  3. 不可逆操作标记
  4. 置信度计算（intent_recognition, entity_binding, parameter_inference）
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
import re


@dataclass
class CompiledIntent:
    """编译后的意图"""
    operation: str
    parameters: Dict[str, Any]
    ambiguity: Optional[Dict[str, Any]] = None
    irreversible: bool = False
    confidence_breakdown: Dict[str, float] = None
    
    def __post_init__(self):
        if self.confidence_breakdown is None:
            self.confidence_breakdown = {}
        
        # 计算overall confidence（取最小值）
        if self.confidence_breakdown:
            self.overall_confidence = min(self.confidence_breakdown.values())
        else:
            self.overall_confidence = 0.5


class IntentCompiler:
    """意图编译器"""
    
    def __init__(self, schema):
        self.schema = schema
    
    def compile(self, intent: str, context: Dict = None) -> CompiledIntent:
        """编译自然语言意图"""
        print(f"\n[IntentCompiler] 编译意图: {intent}")
        
        # Step 1: 意图识别
        intent_type, confidence_intent = self._recognize_intent(intent)
        print(f"  意图类型: {intent_type}, 置信度: {confidence_intent:.2f}")
        
        # Step 2: 实体绑定
        entities, confidence_entity = self._bind_entities(intent, context)
        print(f"  实体绑定: {entities}, 置信度: {confidence_entity:.2f}")
        
        # Step 3: 操作映射
        operation = self._map_to_operation(intent_type)
        
        # Step 4: 参数推断
        parameters, confidence_param = self._infer_parameters(intent, entities)
        print(f"  参数: {parameters}, 置信度: {confidence_param:.2f}")
        
        # Step 5: 检测不可逆操作
        irreversible = self._is_irreversible(operation)
        
        # Step 6: 检测歧义
        ambiguity = self._detect_ambiguity(entities, parameters)
        
        return CompiledIntent(
            operation=operation,
            parameters=parameters,
            ambiguity=ambiguity,
            irreversible=irreversible,
            confidence_breakdown={
                "intent_recognition": confidence_intent,
                "entity_binding": confidence_entity,
                "parameter_inference": confidence_param,
            }
        )
    
    def _recognize_intent(self, intent: str) -> tuple:
        """识别意图类型"""
        intent_lower = intent.lower()
        
        # 关键词匹配
        if any(kw in intent_lower for kw in ["延长", "延期", "续期"]):
            return "extend_validity", 0.92
        elif any(kw in intent_lower for kw in ["修改", "调整", "更新"]):
            return "update_threshold", 0.85
        elif any(kw in intent_lower for kw in ["删除", "移除"]):
            return "delete", 0.95
        elif any(kw in intent_lower for kw in ["查询", "查看", "检查"]):
            return "query", 0.98
        else:
            return "unknown", 0.3
    
    def _bind_entities(self, intent: str, context: Dict = None) -> tuple:
        """实体绑定"""
        entities = {}
        confidence = 0.8
        
        # 简化实现：正则提取供应商ID
        if "Beta" in intent or "beta" in intent:
            entities["supplier_id"] = "S-BETA-002"
            confidence = 0.95
        elif "Alpha" in intent or "alpha" in intent:
            entities["supplier_id"] = "S-ALPHA-001"
            confidence = 0.95
        elif "Gamma" in intent or "gamma" in intent:
            entities["supplier_id"] = "S-GAMMA-003"
            confidence = 0.95
        else:
            # 歧义：供应商不明确
            entities["supplier_id"] = "$UNBOUND"
            confidence = 0.4
        
        return entities, confidence
    
    def _map_to_operation(self, intent_type: str) -> str:
        """意图类型 → 操作"""
        mapping = {
            "extend_validity": "extend_certification_validity",
            "update_threshold": "update_certification_threshold",
            "delete": "delete_supplier",
            "query": "query_supplier_status",
        }
        return mapping.get(intent_type, "unknown_operation")
    
    def _infer_parameters(self, intent: str, entities: Dict) -> tuple:
        """推断参数"""
        parameters = {}
        confidence = 0.85
        
        # 提取数字
        numbers = re.findall(r'\d+', intent)
        
        # 供应商ID
        if entities.get("supplier_id") and entities["supplier_id"] != "$UNBOUND":
            parameters["supplier_id"] = entities["supplier_id"]
        else:
            parameters["supplier_id"] = "$UNBOUND"
            confidence = 0.5
        
        # 延期天数
        if "延长" in intent or "延期" in intent:
            if len(numbers) > 0:
                parameters["extend_days"] = int(numbers[-1])
                confidence = 0.90
            else:
                parameters["extend_days"] = 30  # 默认值
                confidence = 0.70
        
        return parameters, confidence
    
    def _is_irreversible(self, operation: str) -> bool:
        """检查是否不可逆操作"""
        irreversible_ops = ["delete_supplier", "close_account", "terminate_contract"]
        return operation in irreversible_ops
    
    def _detect_ambiguity(self, entities: Dict, parameters: Dict) -> Optional[Dict]:
        """检测歧义"""
        ambiguities = []
        
        for key, value in {**entities, **parameters}.items():
            if value == "$UNBOUND":
                ambiguities.append({
                    "field": key,
                    "reason": "无法从意图中明确绑定"
                })
        
        if ambiguities:
            return {"ambiguities": ambiguities, "require_confirmation": True}
        return None
