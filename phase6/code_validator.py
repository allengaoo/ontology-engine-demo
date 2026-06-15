"""
code_validator — 用 ConstraintMemory 校验生成代码

职责：
  - 从 MemoryGraph 提取 enforcement=reject 的约束
  - 对生成代码执行规则检查（基于 AST 或正则）
  - 返回校验结果：pass/fail + 原因 + 违反的记忆 ID

设计：端侧场景下校验不依赖 LLM，纯规则执行
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import List

from memory_graph import MemoryGraph, MemoryNode


@dataclass
class Violation:
    memory_id: str
    rule: str
    detail: str


@dataclass
class ValidationReport:
    passed: bool
    violations: List[Violation] = field(default_factory=list)
    checks_run: int = 0

    def summary(self) -> str:
        if self.passed:
            return f"✓ PASS ({self.checks_run} checks, 0 violations)"
        return (
            f"✗ FAIL ({self.checks_run} checks, "
            f"{len(self.violations)} violations)"
        )


class CodeValidator:
    """基于 ConstraintMemory 的代码校验器"""

    def __init__(self, graph: MemoryGraph):
        self.graph = graph
        self._constraints = self._load_constraints()

    def _load_constraints(self) -> List[MemoryNode]:
        return [
            n for n in self.graph.all_nodes()
            if n.object_type == "ConstraintMemory"
            and n.meta.get("enforcement") == "reject"
        ]

    def validate(self, code: str) -> ValidationReport:
        report = ValidationReport(passed=True)

        for constraint in self._constraints:
            rule_id = constraint.meta.get("rule_id", constraint.id)
            checker = self._get_checker(constraint)
            if checker:
                report.checks_run += 1
                violation = checker(code, constraint)
                if violation:
                    report.passed = False
                    report.violations.append(violation)

        return report

    def _get_checker(self, constraint: MemoryNode):
        rule_id = constraint.meta.get("rule_id", "")

        if rule_id == "ARCH-001":
            return self._check_layer_dependency

        tags = constraint.tags
        if "import" in tags or "dependency" in tags:
            return self._check_layer_dependency

        return self._check_generic_constraint

    def _check_layer_dependency(self, code: str, constraint: MemoryNode):
        """检查分层依赖违规：领域层不得 import 适配层"""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return None

        adapter_modules = {"adapter", "infrastructure", "kafka_producer", "http_client"}
        domain_indicators = {"service", "domain", "entity", "repository"}

        has_domain_class = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                name_lower = node.name.lower()
                if any(ind in name_lower for ind in domain_indicators):
                    has_domain_class = True
                    break

        if not has_domain_class:
            return None

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(m in alias.name.lower() for m in adapter_modules):
                        return Violation(
                            memory_id=constraint.id,
                            rule=constraint.meta.get("rule_id", ""),
                            detail=f"领域层代码 import 了适配层模块: {alias.name}",
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if any(m in module.lower() for m in adapter_modules):
                    return Violation(
                        memory_id=constraint.id,
                        rule=constraint.meta.get("rule_id", ""),
                        detail=f"领域层代码 from {module} import ...",
                    )

        return None

    def _check_generic_constraint(self, code: str, constraint: MemoryNode):
        """通用约束检查：基于关键词匹配"""
        body = constraint.body.lower()

        forbidden_patterns = []
        if "不得" in body or "禁止" in body:
            for line in body.split("\n"):
                if "不得" in line or "禁止" in line:
                    words = re.findall(r"[a-zA-Z_]+", line)
                    forbidden_patterns.extend(
                        w for w in words if len(w) > 3
                    )

        code_lower = code.lower()
        for pat in forbidden_patterns:
            if pat in code_lower:
                return Violation(
                    memory_id=constraint.id,
                    rule=constraint.meta.get("rule_id", ""),
                    detail=f"代码中出现约束禁止的模式: {pat}",
                )

        return None
