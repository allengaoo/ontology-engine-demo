"""
SchemaLoader - 本体Schema加载器

职责：
- 从YAML文件加载对象类型、操作类型和规则定义
- 作为所有引擎执行的"定义库"

对应Palantir：OMS (Ontology Metadata Service)
"""

import yaml
from pathlib import Path
from typing import Dict, List, Any
from dataclasses import dataclass


@dataclass
class ObjectType:
    """对象类型定义"""
    name: str
    description: str
    properties: Dict[str, Any]


@dataclass
class ActionType:
    """操作类型定义"""
    action_id: str
    description: str
    parameters: Dict[str, Any]
    preconditions: List[Dict[str, str]]
    triggered_rules: List[str]
    effects: List[Dict[str, Any]]


@dataclass
class Rule:
    """全局规则定义"""
    rule_id: str
    description: str
    trigger_on: List[str]
    expression: str
    violation_message: str
    requires_objects: List[Dict[str, Any]]


class SchemaLoader:
    """Schema加载器"""
    
    def __init__(self, schema_dir: Path):
        self.schema_dir = Path(schema_dir)
        self._object_types: Dict[str, ObjectType] = {}
        self._action_types: Dict[str, ActionType] = {}
        self._rules: Dict[str, Rule] = {}
        self._load_all()
    
    def _load_all(self):
        """加载所有schema定义"""
        self._load_object_types()
        self._load_action_types()
        self._load_rules()
    
    def _load_object_types(self):
        """加载对象类型定义"""
        path = self.schema_dir / "object_types.yaml"
        if not path.exists():
            return
        
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        for name, spec in data.get('object_types', {}).items():
            self._object_types[name] = ObjectType(
                name=name,
                description=spec.get('description', ''),
                properties=spec.get('properties', {})
            )
    
    def _load_action_types(self):
        """加载操作类型定义"""
        path = self.schema_dir / "action_types.yaml"
        if not path.exists():
            return
        
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        for action_id, spec in data.get('action_types', {}).items():
            self._action_types[action_id] = ActionType(
                action_id=action_id,
                description=spec.get('description', ''),
                parameters=spec.get('parameters', {}),
                preconditions=spec.get('preconditions', []),
                triggered_rules=spec.get('triggered_rules', []),
                effects=spec.get('effects', [])
            )
    
    def _load_rules(self):
        """加载全局规则定义"""
        path = self.schema_dir / "rules.yaml"
        if not path.exists():
            return
        
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        for rule_spec in data.get('rules', []):
            rule = Rule(
                rule_id=rule_spec['rule_id'],
                description=rule_spec.get('description', ''),
                trigger_on=rule_spec.get('trigger_on', []),
                expression=rule_spec['expression'].strip(),
                violation_message=rule_spec['violation_message'],
                requires_objects=rule_spec.get('requires_objects', [])
            )
            self._rules[rule.rule_id] = rule
    
    def get_object_type(self, name: str) -> ObjectType:
        """获取对象类型定义"""
        if name not in self._object_types:
            raise ValueError(f"对象类型 {name} 未定义")
        return self._object_types[name]
    
    def get_action_type(self, action_id: str) -> ActionType:
        """获取操作类型定义"""
        if action_id not in self._action_types:
            raise ValueError(f"操作类型 {action_id} 未定义")
        return self._action_types[action_id]
    
    def get_rule(self, rule_id: str) -> Rule:
        """获取规则定义"""
        if rule_id not in self._rules:
            raise ValueError(f"规则 {rule_id} 未定义")
        return self._rules[rule_id]
    
    def get_rules_for_action(self, action_id: str) -> List[Rule]:
        """获取某个操作触发的所有规则"""
        action = self.get_action_type(action_id)
        return [self.get_rule(rule_id) for rule_id in action.triggered_rules]
    
    def list_object_types(self) -> List[str]:
        """列出所有对象类型"""
        return list(self._object_types.keys())
    
    def list_action_types(self) -> List[str]:
        """列出所有操作类型"""
        return list(self._action_types.keys())
    
    def list_rules(self) -> List[str]:
        """列出所有规则"""
        return list(self._rules.keys())
