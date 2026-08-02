"""CA 用：从已生成代码提取签名摘要，供后续 Unit 对齐 API。"""

from __future__ import annotations

import ast
import re
from typing import Dict, List


def extract_exports_summary(code: str, *, max_chars: int = 1200) -> str:
    """提取 def/class 签名与简单赋值，失败则退回首尾截断。"""
    code = code or ""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return _truncate(code, max_chars)

    lines: List[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = [
                n.name
                for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ][:12]
            lines.append(f"class {node.name}: methods={methods}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            lines.append(f"def {node.name}({', '.join(args)})")
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    lines.append(f"{t.id} = …")
    if not lines:
        return _truncate(code, max_chars)
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[: max_chars - 20] + "\n…(truncated)"


def format_generated_so_far(
    items: List[Dict[str, str]],
    *,
    max_files: int = 8,
    per_file_chars: int = 900,
) -> str:
    """将本 EP 已生成文件格式化为 CA prompt 段落。"""
    if not items:
        return "（尚无已生成文件）"
    parts: List[str] = []
    for item in items[-max_files:]:
        path = item.get("path", "?")
        summary = item.get("summary") or extract_exports_summary(
            item.get("code", ""), max_chars=per_file_chars
        )
        parts.append(f"### {path}\n{summary}")
    return "\n\n".join(parts)


def _truncate(code: str, max_chars: int) -> str:
    if len(code) <= max_chars:
        return code
    head = max_chars // 2
    return code[:head] + "\n…\n" + code[-(max_chars - head - 10) :]


_IMPORT_HINT_RE = re.compile(
    r"^\s*(?:from|import)\s+(\S+)", re.MULTILINE
)


def list_top_level_imports(code: str) -> List[str]:
    return _IMPORT_HINT_RE.findall(code or "")[:20]
