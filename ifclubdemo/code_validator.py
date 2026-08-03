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
from typing import List, Optional, Set

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


# 路径禁令中常见的“路径片段”，绝不能当关键词去扫源码
_PATH_STOPWORDS: Set[str] = {
    "backend",
    "frontend",
    "src",
    "tests",
    "test",
    "meeting_order",
    "main",
    "models",
    "model",
    "domain",
    "api",
    "scheduler",
    "public",
    "docs",
    "data",
    "acceptance",
    "package",
    "init",
    "index",
    "html",
    "path",
    "paths",
    "file",
    "files",
    "write",
    "open",
    "call",
    "type",
    "slot",
    "name",
    "team",
    "active",
    "list",
    "create",
    "request",
    "detail",
    "code",
    "true",
    "false",
    "none",
    "self",
    "from",
    "import",
    "class",
    "def",
    "return",
    "raise",
    "with",
    "async",
    "await",
    "http",
    "https",
    "json",
    "sqlite",
    "fastapi",
    "react",
    "vite",
    "build",
    "alias",
    "client",
    # 领域/流程词：架构 brief 举例时极易误伤源码
    "booking",
    "room",
    "booker",
    "unit",
    "units",
    "impl",
    "repair",
    "freeze",
    "schema",
    "pytest",
    "primary",
    "backup",
    "target",
    "directory",
    "ep",
}


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

    def validate(self, code: str, *, file_path: str = "") -> ValidationReport:
        report = ValidationReport(passed=True)
        path = (file_path or "").replace("\\", "/")

        for constraint in self._constraints:
            # 「前端不得…」类约束只检查前端文件，避免误杀 backend 的 sqlite
            body = constraint.body or ""
            if ("前端" in body) and ("不得" in body or "禁止" in body):
                if path and "frontend/" not in path:
                    continue
            checker = self._get_checker(constraint)
            if checker:
                report.checks_run += 1
                violation = checker(code, constraint, path)
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

    def _check_layer_dependency(
        self, code: str, constraint: MemoryNode, file_path: str = ""
    ):
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

    @staticmethod
    def _extract_backtick_paths(text: str) -> List[str]:
        """提取约束正文中像文件路径的 `...` 片段。"""
        paths: List[str] = []
        for raw in re.findall(r"`([^`]+)`", text):
            p = raw.strip().replace("\\", "/")
            if not p:
                continue
            # 路径：含 / 或常见源码后缀；排除纯标识符（如 typescript）
            if "/" in p or re.search(
                r"\.(py|ts|tsx|js|jsx|json|toml|md|html|svg|ico)$", p, re.I
            ):
                paths.append(p)
        return paths

    @staticmethod
    def _path_is_forbidden(file_path: str, forbidden: str) -> bool:
        if not file_path or not forbidden:
            return False
        fp = file_path.replace("\\", "/").lstrip("./")
        fb = forbidden.replace("\\", "/").lstrip("./")
        if fp == fb or fp.endswith("/" + fb) or fp.endswith(fb):
            return True
        # 允许约束写 backend/src/main.py，实际 target 也可能是同路径
        if fb.endswith(fp) and ("/" in fp or fp.endswith(".py")):
            return True
        return False

    def _check_generic_constraint(
        self, code: str, constraint: MemoryNode, file_path: str = ""
    ) -> Optional[Violation]:
        """
        通用约束：
          1) 优先按正文反引号中的「整路径」匹配 target_path / 源码中的路径字面量
          2) 其余禁止词仅做词边界匹配，并排除路径片段与常见停用词，避免误伤
        """
        body = constraint.body or ""
        body_lower = body.lower()
        if "不得" not in body_lower and "禁止" not in body_lower:
            return None

        # 显式禁令：@/ 路径别名（不依赖英文抽词）
        if "@/" in body or "路径别名" in body:
            if re.search(r"""['\"]@/|from\s+['\"]@/""", code):
                return Violation(
                    memory_id=constraint.id,
                    rule=constraint.meta.get("rule_id", ""),
                    detail="禁止使用 @/ 路径别名，请改用相对路径 import",
                )

        forbidden_paths = self._extract_backtick_paths(body)
        for fpath in forbidden_paths:
            if self._path_is_forbidden(file_path, fpath):
                return Violation(
                    memory_id=constraint.id,
                    rule=constraint.meta.get("rule_id", ""),
                    detail=f"写入了约束禁止的路径: {fpath}",
                )

        # 写路径 / Unit 文件路径类禁令：只做路径匹配，绝不拆英文词扫源码
        # （否则「禁止目录路径 models/」「如 shift.py」会误伤业务标识符）
        write_path_constraint = (
            "整路径" in body
            or "target_path" in body_lower
            or "目录路径" in body
            or "写路径" in body
            or "禁止创建以下错误写路径" in body
            or ("禁止" in body and "目录" in body and (".py" in body_lower or "unit" in body_lower))
        )
        if write_path_constraint:
            return None

        # 关键词：只从含 禁止/不得 的行提取；排除反引号、文件名、路径片段与停用词
        path_segments: Set[str] = set()
        for p in forbidden_paths:
            for seg in re.findall(r"[a-zA-Z_]{2,}", p):
                path_segments.add(seg.lower())

        forbidden_patterns: List[str] = []
        for line in body.split("\n"):
            line_l = line.lower()
            if "不得" not in line_l and "禁止" not in line_l:
                continue
            # 去掉反引号、文件名与含 / 的路径后再抽词
            cleaned = re.sub(r"`[^`]+`", " ", line)
            cleaned = re.sub(
                r"[A-Za-z0-9_./-]+\.(py|ts|tsx|js|jsx|json|toml|md|html|svg|ico)\b",
                " ",
                cleaned,
                flags=re.I,
            )
            cleaned = re.sub(r"[A-Za-z0-9_]+(?:/[A-Za-z0-9_./-]+)+", " ", cleaned)
            # 裸文件名举例：shift.py（无反引号）
            cleaned = re.sub(
                r"\b[A-Za-z_][A-Za-z0-9_]*\.(py|ts|tsx|js|jsx)\b",
                " ",
                cleaned,
                flags=re.I,
            )
            words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{3,}", cleaned)
            for w in words:
                wl = w.lower()
                if wl in _PATH_STOPWORDS or wl in path_segments:
                    continue
                if wl not in forbidden_patterns:
                    forbidden_patterns.append(wl)

        for pat in forbidden_patterns:
            if re.search(rf"\b{re.escape(pat)}\b", code, flags=re.IGNORECASE):
                return Violation(
                    memory_id=constraint.id,
                    rule=constraint.meta.get("rule_id", ""),
                    detail=f"代码中出现约束禁止的模式: {pat}",
                )

        return None
