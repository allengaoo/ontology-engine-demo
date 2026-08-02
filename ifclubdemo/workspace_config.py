"""
WorkspaceConfig — CLI / EP 共用的工作区配置（TOML 子集，兼容 Python 3.9）。
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_ALLOWED_GLOBS = [
    "src/**",
    "backend/**",
    "frontend/src/**",
    "frontend/public/**",
    "frontend/package.json",
    "frontend/vite.config.*",
    "frontend/tsconfig*.json",
    "frontend/index.html",
    "tests/**",
    "docs/**",
    "data/**",
    "acceptance/**",
    "requirements.txt",
    "README.md",
    "workspace.toml",
    "*.md",
]

DEFAULT_PATH_PREFIXES = [
    "src/",
    "backend/",
    "frontend/src/",
    "frontend/public/",
    "frontend/index.html",
    "tests/",
    "docs/",
    "data/",
]


def _parse_simple_toml(text: str) -> Dict[str, Any]:
    """极简 TOML 子集：字符串、bool、字符串数组。"""
    data: Dict[str, Any] = {}
    section = data
    i = 0
    lines = text.splitlines()
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line.startswith("#"):
            continue
        m_sec = re.match(r"^\[([^\]]+)\]$", line)
        if m_sec:
            # 只取最后一段作为扁平 section 名；本项目只用 [workspace]
            section = data.setdefault(m_sec.group(1).split(".")[-1], {})
            if not isinstance(section, dict):
                section = {}
                data[m_sec.group(1).split(".")[-1]] = section
            continue
        if "=" not in line:
            continue
        key, raw = line.split("=", 1)
        key = key.strip()
        raw = raw.strip()
        if raw.startswith("["):
            buf = raw
            while buf.count("[") > buf.count("]") and i < len(lines):
                buf += lines[i]
                i += 1
            try:
                section[key] = ast.literal_eval(buf.replace("\n", " "))
            except (SyntaxError, ValueError):
                section[key] = []
            continue
        if raw.lower() in ("true", "false"):
            section[key] = raw.lower() == "true"
            continue
        if (raw.startswith('"') and raw.endswith('"')) or (
            raw.startswith("'") and raw.endswith("'")
        ):
            section[key] = raw[1:-1]
            continue
        section[key] = raw
    return data


@dataclass
class WorkspaceConfig:
    name: str = "app"
    root: Path = field(default_factory=lambda: Path("."))
    allowed_write_globs: List[str] = field(
        default_factory=lambda: list(DEFAULT_ALLOWED_GLOBS)
    )
    allowed_path_prefixes: List[str] = field(
        default_factory=lambda: list(DEFAULT_PATH_PREFIXES)
    )
    app_entry: str = ""
    frontend_dir: str = "frontend"
    frontend_dev_cmd: str = "npm run dev"
    frontend_build_cmd: str = "npm run build"
    test_cmd: str = "pytest -q tests"
    domain_memory_dir: str = ".ontology_agent/memory"
    arch_memory_dir: str = ".ontology_agent/arch_memory"
    business_brief: str = "docs/business_brief.md"
    architecture_brief: str = "docs/architecture_brief.md"
    run_pytest: bool = True

    @classmethod
    def load(cls, workspace_root: Path) -> "WorkspaceConfig":
        root = Path(workspace_root).resolve()
        cfg_path = root / "workspace.toml"
        section: Dict[str, Any] = {}
        if cfg_path.exists():
            parsed = _parse_simple_toml(cfg_path.read_text(encoding="utf-8"))
            section = parsed.get("workspace", parsed) or {}
        return cls(
            name=str(section.get("name", root.name)),
            root=root,
            allowed_write_globs=list(
                section.get("allowed_write_globs", DEFAULT_ALLOWED_GLOBS)
            ),
            allowed_path_prefixes=list(
                section.get("allowed_path_prefixes", DEFAULT_PATH_PREFIXES)
            ),
            app_entry=str(section.get("app_entry", "")),
            frontend_dir=str(section.get("frontend_dir", "frontend")),
            frontend_dev_cmd=str(section.get("frontend_dev_cmd", "npm run dev")),
            frontend_build_cmd=str(
                section.get("frontend_build_cmd", "npm run build")
            ),
            test_cmd=str(section.get("test_cmd", "pytest -q tests")),
            domain_memory_dir=str(
                section.get("domain_memory_dir", ".ontology_agent/memory")
            ),
            arch_memory_dir=str(
                section.get("arch_memory_dir", ".ontology_agent/arch_memory")
            ),
            business_brief=str(
                section.get("business_brief", "docs/business_brief.md")
            ),
            architecture_brief=str(
                section.get(
                    "architecture_brief", "docs/architecture_brief.md"
                )
            ),
            run_pytest=bool(section.get("run_pytest", True)),
        )

    def save(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / "workspace.toml"
        globs = "\n".join(f'  "{g}",' for g in self.allowed_write_globs)
        prefixes = "\n".join(f'  "{p}",' for p in self.allowed_path_prefixes)
        text = f"""# Ontology Agent workspace config
[workspace]
name = "{self.name}"
app_entry = "{self.app_entry}"
frontend_dir = "{self.frontend_dir}"
frontend_dev_cmd = "{self.frontend_dev_cmd}"
frontend_build_cmd = "{self.frontend_build_cmd}"
test_cmd = "{self.test_cmd}"
domain_memory_dir = "{self.domain_memory_dir}"
arch_memory_dir = "{self.arch_memory_dir}"
business_brief = "{self.business_brief}"
architecture_brief = "{self.architecture_brief}"
run_pytest = {str(self.run_pytest).lower()}

allowed_write_globs = [
{globs}
]

allowed_path_prefixes = [
{prefixes}
]
"""
        path.write_text(text, encoding="utf-8")
        return path
