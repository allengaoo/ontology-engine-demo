"""
Phase 6 包：记忆本体内核

端侧小模型 + YAML 本体驱动的记忆系统骨架：
  OntologyRegistry   — Schema 加载与实例校验
  MemoryGraph        — 实例图、概念/规则反向索引
  HybridSearch       — 图优先检索 + 关键词降级
  MemoryInjector     — tier 策略注入 + InjectManifest
  MemoryActions      — 校验后写入 / deprecated
  LLMCoder           — 调用端侧模型生成代码
  CodeValidator      — ConstraintMemory 执法校验
  schema_evolution   — 健康度分析（骨架）

入口：run_phase6_demo.py（端到端编码闭环演示）
"""

from .ontology_registry import OntologyRegistry, ValidationResult
from .memory_graph import MemoryGraph, MemoryNode
from .hybrid_search import HybridSearch
from .memory_injector import MemoryInjector, InjectManifest
from .memory_actions import MemoryActions
from .llm_coder import LLMCoder, CodeGenResult
from .code_validator import CodeValidator, ValidationReport

__all__ = [
    "OntologyRegistry", "ValidationResult",
    "MemoryGraph", "MemoryNode",
    "HybridSearch",
    "MemoryInjector", "InjectManifest",
    "MemoryActions",
    "LLMCoder", "CodeGenResult",
    "CodeValidator", "ValidationReport",
]
