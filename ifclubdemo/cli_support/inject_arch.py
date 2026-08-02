"""
从架构说明 Markdown 生成工作区级架构记忆（code-arch）。

落盘：workspace/.ontology_agent/arch_memory/
未 inject 时，EP 回退到包内精简种子 ifclubdemo/instances/。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class InjectItem:
    memory_id: str
    object_type: str
    path: str
    title: str


@dataclass
class InjectReport:
    source: str
    items: List[InjectItem] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "dry_run": self.dry_run,
            "kind": "architecture",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "items": [
                {
                    "memory_id": i.memory_id,
                    "object_type": i.object_type,
                    "path": i.path,
                    "title": i.title,
                }
                for i in self.items
            ],
        }


# section 关键词 → (object_type, prefix, enforcement, layer)
# 注意：更长的键优先匹配（避免「模式」误伤「反模式」）
SECTION_MAP = {
    "反模式": ("AntiPatternMemory", "ANTI", "", "DOMAIN"),
    "推荐模式": ("PatternMemory", "PAT", "", "CROSS_CUTTING"),
    "推荐": ("PatternMemory", "PAT", "", "CROSS_CUTTING"),
    "分层": ("ConstraintMemory", "CN", "reject", "CROSS_CUTTING"),
    "写路径": ("ConstraintMemory", "CN", "reject", "CROSS_CUTTING"),
    "写范围": ("ConstraintMemory", "CN", "reject", "CROSS_CUTTING"),
    "验证": ("ConstraintMemory", "CN", "reject", "CROSS_CUTTING"),
    "前端": ("ConstraintMemory", "CN", "reject", "CROSS_CUTTING"),
}


def _extract_sections(text: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^##\s+(?:\d+\.\s*)?(.+)$", line.strip())
        if m:
            current = m.group(1).strip()
            current = re.sub(r"（.*?）|\(.*?\)", "", current).strip()
            sections.setdefault(current, [])
            continue
        if current is None:
            continue
        bullet = re.match(r"^[-*]\s+(.+)$", line.strip())
        if bullet:
            sections[current].append(bullet.group(1).strip())
    return sections


def _match_section(name: str) -> Optional[Tuple[str, str, str, str]]:
    # 最长键优先，避免「模式」命中「反模式」
    for key, meta in sorted(SECTION_MAP.items(), key=lambda kv: -len(kv[0])):
        if key in name:
            return meta
    return None


def _yaml_str(value: str) -> str:
    """Quote a scalar so backticks / braces / colons in titles don't break YAML."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_memory(
    *,
    memory_id: str,
    object_type: str,
    title: str,
    layer: str,
    enforcement: str,
    body: str,
    source_file: str,
) -> str:
    enf = f"\nenforcement: {enforcement}" if enforcement else ""
    rule = ""
    if object_type == "ConstraintMemory":
        # schema 要求 rule_id；用记忆 id 充当稳定规则标识
        rule = f"\nrule_id: {memory_id}"
    return f"""---
id: {memory_id}
object_type: {object_type}
title: {_yaml_str(title)}
layer: {layer}
tier: hot
tags:
- architecture
- injected
confidence: 0.9
schema_version: 1
status: active{rule}{enf}
source: {source_file}
---

## HOW

{body}

## WHEN

由架构说明 inject-arch 生成；改代码结构 / 写路径时必查。
"""


def inject_architecture_brief(
    brief_path: Path,
    memory_dir: Path,
    *,
    dry_run: bool = False,
) -> InjectReport:
    brief_path = Path(brief_path).resolve()
    memory_dir = Path(memory_dir).resolve()
    text = brief_path.read_text(encoding="utf-8")
    sections = _extract_sections(text)
    report = InjectReport(source=str(brief_path), dry_run=dry_run)

    counters = {"CN": 0, "PAT": 0, "ANTI": 0}

    for section_name, bullets in sections.items():
        meta = _match_section(section_name)
        if not meta or not bullets:
            continue
        object_type, prefix, enforcement, layer = meta
        for bullet in bullets:
            counters[prefix] += 1
            mid = f"{prefix}-ARCH-WS-{counters[prefix]:03d}"
            rel = f"{layer}/{mid}.md"
            abs_path = memory_dir / rel
            content = _render_memory(
                memory_id=mid,
                object_type=object_type,
                title=bullet[:80],
                layer=layer,
                enforcement=enforcement,
                body=bullet,
                source_file=brief_path.name,
            )
            report.items.append(
                InjectItem(
                    memory_id=mid,
                    object_type=object_type,
                    path=str(abs_path),
                    title=bullet[:80],
                )
            )
            if not dry_run:
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                abs_path.write_text(content, encoding="utf-8")

    if not dry_run:
        memory_dir.mkdir(parents=True, exist_ok=True)
        report_path = memory_dir.parent / "inject_arch_report.json"
        report_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return report
