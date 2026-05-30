"""
Ontology Demo Engine - 最小本体引擎

这是"工程师的本体论"系列第5篇的完整实现
展示了决策治理系统的核心逻辑

核心组件：
- SchemaLoader: 加载YAML定义
- ObjectStore: 对象存储（JSON文件）
- RuleEngine: 规则校验
- ActionEngine: 操作执行协调器
- AuditLogger: 决策日志

关键设计决策（第5篇）：
1. 规则在写入"后"执行（检查新状态）
2. 日志存快照而不是diff（可追溯决策上下文）
3. Schema用YAML而不是Python类（业务文档）
"""

from .schema_loader import SchemaLoader
from .object_store import ObjectStore
from .rule_engine import RuleEngine
from .action_engine import ActionEngine
from .audit_logger import AuditLogger

__all__ = [
    'SchemaLoader',
    'ObjectStore',
    'RuleEngine',
    'ActionEngine',
    'AuditLogger',
]

__version__ = '0.1.0'
