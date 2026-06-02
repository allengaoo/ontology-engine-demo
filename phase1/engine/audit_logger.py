"""
AuditLogger - 审计日志记录器

职责：
- 记录每次操作的完整决策上下文
- 追加式写入JSONL文件（每行一个JSON事件）
- 记录快照而不是diff（第5篇"第二个决策"）

对应Palantir：操作服务（日志部分）

设计说明：
- 使用JSONL格式（JSON Lines）：每行一个完整的JSON对象
- 记录操作时的对象快照、通过的规则、执行结果
- 这样三个月后能完整还原"AI当时为什么这样决定"
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict
import uuid


@dataclass
class DecisionEvent:
    """
    决策事件
    
    这是第5篇"第二个决策"的核心数据结构：
    - 不只记录"做了什么"（diff）
    - 而是记录"为什么这样做"（完整上下文快照）
    """
    event_id: str              # 事件唯一ID
    action_id: str             # 操作类型
    caller: str                # 调用方（Agent/用户）
    params: Dict[str, Any]     # 操作参数
    
    # 核心：执行时的对象快照（不是diff！）
    snapshot: Dict[str, Any]
    
    # 规则校验结果
    passed_rules: List[str]    # 通过的规则列表
    outcome: str               # 结果：success / rejected
    rejection_reason: Optional[str] = None
    triggered_rule: Optional[str] = None
    
    # 时间戳
    executed_at: str = None
    
    def __post_init__(self):
        if self.executed_at is None:
            self.executed_at = datetime.now().isoformat()


class AuditLogger:
    """审计日志记录器"""
    
    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "decisions.jsonl"
    
    def log_decision(
        self,
        action_id: str,
        caller: str,
        params: Dict[str, Any],
        snapshot: Dict[str, Any],
        outcome: str,
        passed_rules: List[str] = None,
        rejection_reason: str = None,
        triggered_rule: str = None
    ) -> str:
        """
        记录一次决策事件
        
        返回事件ID
        """
        event = DecisionEvent(
            event_id=f"evt-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}",
            action_id=action_id,
            caller=caller,
            params=params,
            snapshot=snapshot,
            passed_rules=passed_rules or [],
            outcome=outcome,
            rejection_reason=rejection_reason,
            triggered_rule=triggered_rule
        )
        
        # 追加写入JSONL文件
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(asdict(event), ensure_ascii=False) + '\n')
        
        return event.event_id
    
    def query_events(
        self,
        action_id: Optional[str] = None,
        caller: Optional[str] = None,
        outcome: Optional[str] = None,
        limit: int = 100
    ) -> List[DecisionEvent]:
        """
        查询决策事件
        
        这是第6篇会展示的审计查询能力
        """
        if not self.log_file.exists():
            return []
        
        events = []
        with open(self.log_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    
                    # 过滤
                    if action_id and data.get('action_id') != action_id:
                        continue
                    if caller and data.get('caller') != caller:
                        continue
                    if outcome and data.get('outcome') != outcome:
                        continue
                    
                    event = DecisionEvent(**data)
                    events.append(event)
                    
                    if len(events) >= limit:
                        break
                
                except json.JSONDecodeError:
                    continue
        
        return events
    
    def get_event_by_id(self, event_id: str) -> Optional[DecisionEvent]:
        """根据事件ID查询单个事件"""
        if not self.log_file.exists():
            return None
        
        with open(self.log_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    if data.get('event_id') == event_id:
                        return DecisionEvent(**data)
                except json.JSONDecodeError:
                    continue
        
        return None
    
    def count_violations(self, rule_id: str) -> int:
        """
        统计某条规则被违反的次数
        
        用于评估规则有效性（第11篇会展开）
        """
        count = 0
        if not self.log_file.exists():
            return 0
        
        with open(self.log_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    if (data.get('outcome') == 'rejected' and 
                        data.get('triggered_rule') == rule_id):
                        count += 1
                except json.JSONDecodeError:
                    continue
        
        return count
