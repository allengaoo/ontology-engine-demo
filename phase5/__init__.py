"""
Phase 5 包初始化

从原型到生产的完整实现：
  意图编译器（intent_compiler.py）          — 非确定性编译
  置信度引擎（confidence_engine.py）        — 跨层置信度传播
  注入防御（injection_guard.py）           — Prompt Injection防御
  Schema更新器（schema_updater.py）        — 活Schema + 记忆级联

入口：run_phase5_demo.py（完整AI OS演示）
"""

from .intent_compiler import IntentCompiler, CompiledIntent
from .confidence_engine import ConfidenceEngine, ConfidenceTrace
from .injection_guard import InjectionGuard, SanitizationResult
from .schema_updater import SchemaUpdater, SchemaChangeEvent

__all__ = [
    "IntentCompiler", "CompiledIntent",
    "ConfidenceEngine", "ConfidenceTrace",
    "InjectionGuard", "SanitizationResult",
    "SchemaUpdater", "SchemaChangeEvent",
]
