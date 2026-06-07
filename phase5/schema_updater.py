"""
Schema Updater：活Schema更新器

功能：
  1. Schema版本管理
  2. 记忆级联（Schema变更触发相关记忆更新）
  3. 渐进式生效
  4. 回溯查询支持
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime


@dataclass
class SchemaChangeEvent:
    """Schema变更事件"""
    rule_id: str
    old_version: int
    new_version: int
    changes: Dict[str, any]
    timestamp: datetime
    affected_memories: int = 0


class SchemaUpdater:
    """Schema更新器"""
    
    def __init__(self, memory_store=None):
        self.memory_store = memory_store
        self.change_history = []
        self.version_snapshots = {}  # version -> schema_snapshot
    
    def update_rule(
        self,
        rule_id: str,
        old_rule: Dict,
        new_rule: Dict
    ) -> SchemaChangeEvent:
        """更新规则，触发记忆级联"""
        print(f"\n[SchemaUpdater] 更新规则 {rule_id}")
        print(f"  旧值: {old_rule}")
        print(f"  新值: {new_rule}")
        
        # Step 1: 版本递增
        old_version = old_rule.get("version", 1)
        new_version = old_version + 1
        new_rule["version"] = new_version
        
        # Step 2: 记录变更事件
        changes = self._compute_changes(old_rule, new_rule)
        event = SchemaChangeEvent(
            rule_id=rule_id,
            old_version=old_version,
            new_version=new_version,
            changes=changes,
            timestamp=datetime.now()
        )
        
        # Step 3: 触发记忆级联
        if self.memory_store:
            affected_count = self._cascade_memory_update(rule_id, old_rule, new_rule)
            event.affected_memories = affected_count
            print(f"  影响记忆: {affected_count}条")
        
        # Step 4: 保存版本快照
        self.version_snapshots[new_version] = new_rule.copy()
        
        # Step 5: 记录变更历史
        self.change_history.append(event)
        
        print(f"  ✓ 规则更新完成（v{old_version} → v{new_version}）")
        
        return event
    
    def _compute_changes(self, old_rule: Dict, new_rule: Dict) -> Dict:
        """计算规则变更"""
        changes = {}
        
        for key in set(old_rule.keys()) | set(new_rule.keys()):
            old_value = old_rule.get(key)
            new_value = new_rule.get(key)
            
            if old_value != new_value:
                changes[key] = {
                    "from": old_value,
                    "to": new_value
                }
        
        return changes
    
    def _cascade_memory_update(
        self,
        rule_id: str,
        old_rule: Dict,
        new_rule: Dict
    ) -> int:
        """记忆级联更新"""
        if not self.memory_store:
            return 0
        
        # 查找所有引用该规则的记忆
        related_memories = self.memory_store.find_by_rule(rule_id)
        
        affected_count = 0
        for memory in related_memories:
            # 判断记忆与新规则的冲突程度
            conflict = self._detect_conflict(memory, old_rule, new_rule)
            
            if conflict == "contradicts":
                # 完全矛盾 → 标记deprecated
                self.memory_store.deprecate(
                    memory.id,
                    reason=f"规则{rule_id}变更，内容矛盾"
                )
                affected_count += 1
            
            elif conflict == "partial":
                # 部分矛盾 → 降低置信度
                self.memory_store.update_confidence(
                    memory.id,
                    confidence=memory.confidence * 0.7
                )
                affected_count += 1
        
        # 写入新规则到CRITICAL层（如果memory_store支持）
        if hasattr(self.memory_store, 'write'):
            self.memory_store.write(
                content=new_rule.get("description", ""),
                layer="CRITICAL",
                tags=[f"rule:{rule_id}", "schema_seed"],
                confidence=1.0,
                source="schema_update"
            )
        
        return affected_count
    
    def _detect_conflict(
        self,
        memory: any,
        old_rule: Dict,
        new_rule: Dict
    ) -> str:
        """检测记忆与新规则的冲突"""
        # 简化实现：关键词匹配
        memory_content = getattr(memory, 'content', '')
        
        # 检查是否提到旧阈值
        old_threshold = old_rule.get("threshold")
        new_threshold = new_rule.get("threshold")
        
        if old_threshold and str(old_threshold) in memory_content:
            return "contradicts"
        
        if "低于" in memory_content or "不满足" in memory_content:
            return "partial"
        
        return "none"
    
    def get_snapshot(self, version: int) -> Optional[Dict]:
        """获取指定版本的Schema快照"""
        return self.version_snapshots.get(version)
    
    def get_change_history(self) -> List[SchemaChangeEvent]:
        """获取变更历史"""
        return self.change_history
