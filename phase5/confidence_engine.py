"""
Confidence Engine：置信度引擎

功能：
  1. 跨层置信度传播（Layer 6 → Layer 2）
  2. LLM置信度衰减
  3. 操作结果反馈驱动置信度调整
  4. 置信度轨迹记录
"""

from dataclasses import dataclass, field
from typing import List, Dict
from datetime import datetime


@dataclass
class ConfidenceTrace:
    """置信度轨迹"""
    operation_id: str
    traces: List[Dict] = field(default_factory=list)
    final_confidence: float = 0.0
    
    def add_trace(self, layer: str, confidence: float, reason: str = ""):
        """添加置信度轨迹点"""
        self.traces.append({
            "layer": layer,
            "confidence": confidence,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        })
        self.final_confidence = confidence


class ConfidenceEngine:
    """置信度引擎"""
    
    # LLM衰减系数
    LLM_DECAY_FACTOR = 0.7
    
    def __init__(self):
        self.traces = {}  # operation_id -> ConfidenceTrace
    
    def start_trace(self, operation_id: str) -> ConfidenceTrace:
        """开始记录置信度轨迹"""
        trace = ConfidenceTrace(operation_id=operation_id)
        self.traces[operation_id] = trace
        return trace
    
    def propagate(
        self,
        operation_id: str,
        layer: str,
        confidence: float,
        reason: str = ""
    ) -> float:
        """置信度跨层传播"""
        trace = self.traces.get(operation_id)
        if not trace:
            trace = self.start_trace(operation_id)
        
        # Layer特定的调整
        adjusted_confidence = self._apply_layer_adjustment(layer, confidence)
        
        # 记录轨迹
        trace.add_trace(layer, adjusted_confidence, reason)
        
        return adjusted_confidence
    
    def _apply_layer_adjustment(self, layer: str, confidence: float) -> float:
        """应用层级特定的置信度调整"""
        
        if layer == "LLM":
            # LLM层：衰减（防止过度自信）
            adjusted = confidence * self.LLM_DECAY_FACTOR
            
            # 极端值处理
            if confidence > 0.95:
                adjusted = 0.85  # 强制拉低"过于自信"的输出
            elif confidence < 0.3:
                adjusted = 0.1   # 低置信度进一步降低
            
            return adjusted
        
        elif layer == "SimAgent":
            # SimAgent是确定性验证，置信度高
            return min(confidence * 1.1, 0.95)
        
        elif layer == "OntologyKernel":
            # 本体层是最终仲裁
            return confidence
        
        else:
            # 其他层：保持不变
            return confidence
    
    def aggregate_multi_agent(
        self,
        operation_id: str,
        agent_confidences: Dict[str, float]
    ) -> float:
        """汇总多Agent置信度"""
        # 加权平均
        weights = {
            "IntentAgent": 0.2,
            "OntologyAgent": 0.4,
            "SimAgent": 0.4,
        }
        
        total = 0.0
        for agent_name, confidence in agent_confidences.items():
            weight = weights.get(agent_name, 0.33)
            total += confidence * weight
        
        # 记录轨迹
        self.propagate(
            operation_id,
            "Multi-Agent-Aggregate",
            total,
            f"加权平均: {agent_confidences}"
        )
        
        return total
    
    def feedback_adjustment(
        self,
        operation_id: str,
        result: str,
        current_confidence: float
    ) -> float:
        """根据操作结果调整置信度"""
        
        if result == "success":
            # 成功 → 小幅提升
            new_confidence = min(current_confidence + 0.05, 1.0)
            reason = "操作成功，置信度提升"
        
        elif result == "rejected":
            # 拒绝 → 大幅下降
            new_confidence = max(current_confidence - 0.15, 0.1)
            reason = "操作被拒绝，置信度下降"
        
        elif result == "user_corrected":
            # 用户纠正 → 清零
            new_confidence = 0.0
            reason = "用户纠正，置信度清零"
        
        else:
            new_confidence = current_confidence
            reason = "未知结果"
        
        # 记录反馈调整
        self.propagate(
            operation_id,
            "Feedback-Adjustment",
            new_confidence,
            reason
        )
        
        return new_confidence
    
    def get_trace(self, operation_id: str) -> ConfidenceTrace:
        """获取置信度轨迹"""
        return self.traces.get(operation_id)
    
    def should_auto_execute(self, confidence: float, operation_type: str) -> bool:
        """判断是否自动执行"""
        # 不同操作类型的阈值
        thresholds = {
            "query": 0.5,      # 查询操作：低阈值
            "low_risk": 0.75,  # 低风险写操作
            "medium_risk": 0.85,  # 中风险写操作
            "high_risk": 0.95,    # 高风险写操作
            "irreversible": 1.1,  # 不可逆操作：任何置信度都需要人工确认
        }
        
        threshold = thresholds.get(operation_type, 0.75)
        return confidence >= threshold
