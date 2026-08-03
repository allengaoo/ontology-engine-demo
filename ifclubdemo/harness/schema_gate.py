"""
schema_gate — meeting_order 领域 Object 硬校验（零 LLM）

对照 docs/meeting_schema.json（或 workspace 副本）：
  - required_fields 必须出现在 dataclass / 类体中
  - forbidden_fields 不得作为属性名出现
失败 → VerifyOutcome.FAIL_STRUCT（逼 BSA 按契约重规划）
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence


@dataclass
class SchemaViolation:
    model: str
    detail: str


@dataclass
class SchemaCheckResult:
    ok: bool
    violations: List[SchemaViolation] = field(default_factory=list)
    checks_run: int = 0

    def summary(self) -> str:
        if self.ok:
            return f"✓ SCHEMA PASS ({self.checks_run} checks)"
        return (
            f"✗ SCHEMA FAIL ({len(self.violations)}): "
            + "; ".join(f"{v.model}: {v.detail}" for v in self.violations[:5])
        )


def resolve_schema_path(workspace_root: Path) -> Optional[Path]:
    root = Path(workspace_root).resolve()
    candidates = [
        root / "docs" / "meeting_schema.json",
        root / ".ontology_agent" / "meeting_schema.json",
        Path(__file__).resolve().parents[1] / "docs" / "meeting_schema.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def load_schema(workspace_root: Path) -> Optional[dict]:
    path = resolve_schema_path(workspace_root)
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _class_field_names(source: str, class_name: str) -> Optional[set]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            names = set()
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    names.add(stmt.target.id)
                elif isinstance(stmt, ast.Assign):
                    for t in stmt.targets:
                        if isinstance(t, ast.Name):
                            names.add(t.id)
            return names
    # 宽松：全文搜 dataclass 字段赋值
    return None


def _field_mentioned(source: str, field: str) -> bool:
    # 属性注解 / self.field / 构造关键字
    patterns = [
        rf"\b{re.escape(field)}\s*:",
        rf"\b{re.escape(field)}\s*=",
        rf"['\"]{re.escape(field)}['\"]",
    ]
    return any(re.search(p, source) for p in patterns)


class SchemaGate:
    """对照 meeting_schema.json 检查 models（及 diffs 中的同名文件）。"""

    def check(
        self,
        workspace_root: Path,
        *,
        diffs: Optional[Sequence] = None,
    ) -> SchemaCheckResult:
        schema = load_schema(workspace_root)
        if not schema:
            return SchemaCheckResult(ok=True, checks_run=0)

        models: Dict[str, dict] = schema.get("models") or {}
        result = SchemaCheckResult(ok=True)
        root = Path(workspace_root).resolve()

        # diffs 覆盖同路径时优先用生成代码（落盘前/回滚后也能检）
        diff_code: Dict[str, str] = {}
        if diffs:
            for d in diffs:
                rel = getattr(d, "target_path", "") or ""
                rel = rel.replace("\\", "/").lstrip("./")
                code = getattr(d, "code", None)
                if rel and isinstance(code, str):
                    diff_code[rel] = code

        for model_name, spec in models.items():
            rel = (spec.get("path") or "").replace("\\", "/").lstrip("./")
            if not rel:
                continue
            source = diff_code.get(rel)
            if source is None:
                path = root / rel
                if not path.exists():
                    continue  # 尚未生成，跳过
                source = path.read_text(encoding="utf-8", errors="replace")

            result.checks_run += 1
            field_names = _class_field_names(source, model_name)
            required = spec.get("required_fields") or {}
            forbidden = spec.get("forbidden_fields") or []

            for fname in required:
                present = (
                    fname in field_names
                    if field_names is not None
                    else _field_mentioned(source, fname)
                )
                if not present:
                    result.ok = False
                    result.violations.append(
                        SchemaViolation(
                            model_name,
                            f"缺少必填字段 {fname}（path={rel}）",
                        )
                    )

            for fname in forbidden:
                present = (
                    fname in field_names
                    if field_names is not None
                    else _field_mentioned(source, fname)
                )
                if present:
                    result.ok = False
                    result.violations.append(
                        SchemaViolation(
                            model_name,
                            f"出现禁止字段 {fname}（path={rel}）",
                        )
                    )

        # DTO / schemas 段（CreateBookingRequest 等）
        schema_dtos: Dict[str, dict] = schema.get("schemas") or {}
        for dto_name, spec in schema_dtos.items():
            rel = (spec.get("path") or "").replace("\\", "/").lstrip("./")
            if not rel:
                continue
            source = diff_code.get(rel)
            if source is None:
                path = root / rel
                if not path.exists():
                    continue
                source = path.read_text(encoding="utf-8", errors="replace")

            result.checks_run += 1
            field_names = _class_field_names(source, dto_name)
            for fname in spec.get("required_fields") or []:
                present = (
                    fname in field_names
                    if field_names is not None
                    else _field_mentioned(source, fname)
                )
                if not present:
                    result.ok = False
                    result.violations.append(
                        SchemaViolation(
                            dto_name,
                            f"DTO 缺少必填字段 {fname}（path={rel}）",
                        )
                    )
            for fname in spec.get("forbidden_fields") or []:
                present = (
                    fname in field_names
                    if field_names is not None
                    else _field_mentioned(source, fname)
                )
                if present:
                    result.ok = False
                    result.violations.append(
                        SchemaViolation(
                            dto_name,
                            f"DTO 出现禁止字段 {fname}（path={rel}）",
                        )
                    )

        # 前端白名单：components / pages 不得出现名单外文件
        fe = schema.get("frontend") or {}
        allow = set(fe.get("pages_allowlist") or []) | set(
            fe.get("components_allowlist") or []
        )
        if allow:
            for sub in ("pages", "components"):
                d = root / "frontend" / "src" / sub
                if not d.is_dir():
                    continue
                for p in d.glob("*.tsx"):
                    rel = p.relative_to(root).as_posix()
                    result.checks_run += 1
                    if rel not in allow:
                        result.ok = False
                        result.violations.append(
                            SchemaViolation(
                                "frontend_allowlist",
                                f"不在白名单的前端文件：{rel}",
                            )
                        )

        return result
