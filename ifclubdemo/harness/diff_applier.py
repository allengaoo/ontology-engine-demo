"""
diff_applier — 将 UnitDiff 安全落盘到 workspace（Phase 8 P0）

写前备份到 .ontology_agent/backup/<ep_id>/，支持按 ep_id 回滚。
"""

from __future__ import annotations

import fnmatch
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from agents.coding_agent import UnitDiff
from harness.freeze_state import is_frozen


DEFAULT_ALLOWED_GLOBS = (
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
)


@dataclass
class ApplyItem:
    target_path: str
    abs_path: str
    status: str  # written | skipped | failed
    detail: str = ""
    backup_path: str = ""


@dataclass
class ApplyReport:
    ep_id: str
    workspace_root: str
    items: List[ApplyItem] = field(default_factory=list)

    @property
    def written(self) -> List[ApplyItem]:
        return [i for i in self.items if i.status == "written"]

    @property
    def failed(self) -> List[ApplyItem]:
        return [i for i in self.items if i.status == "failed"]

    @property
    def ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        return (
            f"ApplyReport ep={self.ep_id} "
            f"written={len(self.written)} failed={len(self.failed)} "
            f"total={len(self.items)}"
        )


class DiffApplier:
    """将 UnitDiff 写入 workspace，并做路径安全与白名单检查。"""

    def __init__(
        self,
        workspace_root: Path,
        *,
        allowed_globs: Optional[Sequence[str]] = None,
        frozen_prefixes: Optional[Sequence[str]] = None,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.allowed_globs = tuple(allowed_globs or DEFAULT_ALLOWED_GLOBS)
        self.frozen_prefixes: List[str] = list(frozen_prefixes or [])
        self.backup_root = self.workspace_root / ".ontology_agent" / "backup"
        self.scratch_root = self.workspace_root / ".ontology_agent" / "scratch"

    def set_frozen_prefixes(self, prefixes: Optional[Sequence[str]]) -> None:
        self.frozen_prefixes = list(prefixes or [])

    def apply(
        self,
        diffs: Sequence[UnitDiff],
        *,
        ep_id: str,
        dry_run: bool = False,
    ) -> ApplyReport:
        report = ApplyReport(ep_id=ep_id, workspace_root=str(self.workspace_root))
        backup_dir = self.backup_root / ep_id
        if not dry_run:
            backup_dir.mkdir(parents=True, exist_ok=True)

        for diff in diffs:
            item = self._apply_one(diff, backup_dir=backup_dir, dry_run=dry_run)
            report.items.append(item)
        return report

    def save_scratch(self, diffs: Sequence[UnitDiff], *, ep_id: str) -> Path:
        """
        验证失败回滚前，把本轮将回滚掉的内容保存到 scratch，
        供下一轮 CA 作为「待修代码」读取（避免失忆）。
        """
        scratch_dir = self.scratch_root / ep_id
        if scratch_dir.exists():
            shutil.rmtree(scratch_dir)
        scratch_dir.mkdir(parents=True, exist_ok=True)
        for diff in diffs:
            rel = self._normalize_rel(diff.target_path)
            if rel is None:
                continue
            dest = scratch_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(diff.code, encoding="utf-8")
        meta = scratch_dir / "_SCRATCH_META.txt"
        meta.write_text(
            f"ep_id={ep_id}\nfiles={len(diffs)}\n",
            encoding="utf-8",
        )
        return scratch_dir

    def rollback(self, ep_id: str) -> List[str]:
        """用 backup 恢复该 EP 写入过的文件；若备份为 .deleted 标记则删除目标。"""
        backup_dir = self.backup_root / ep_id
        restored: List[str] = []
        if not backup_dir.exists():
            return restored

        for bak in sorted(backup_dir.rglob("*")):
            if bak.is_dir():
                continue
            rel = bak.relative_to(backup_dir)
            # 约定：path + ".deleted" 表示原先不存在
            if str(rel).endswith(".deleted"):
                target_rel = Path(str(rel)[: -len(".deleted")])
                target = self.workspace_root / target_rel
                if target.exists():
                    target.unlink()
                    restored.append(str(target_rel))
                continue
            target = self.workspace_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bak, target)
            restored.append(str(rel))
        return restored

    def _apply_one(
        self,
        diff: UnitDiff,
        *,
        backup_dir: Path,
        dry_run: bool,
    ) -> ApplyItem:
        rel = self._normalize_rel(diff.target_path)
        if rel is None:
            return ApplyItem(
                target_path=diff.target_path,
                abs_path="",
                status="failed",
                detail="非法路径（越界或空）",
            )
        if not self._allowed(rel):
            return ApplyItem(
                target_path=rel,
                abs_path="",
                status="failed",
                detail=f"不在白名单 {self.allowed_globs}",
            )
        if is_frozen(rel, self.frozen_prefixes):
            return ApplyItem(
                target_path=rel,
                abs_path="",
                status="failed",
                detail=f"路径已 freeze，禁止写入: {rel}",
            )

        abs_path = self.workspace_root / rel
        name = Path(rel).name
        if rel.endswith("/") or "." not in name:
            return ApplyItem(
                target_path=rel,
                abs_path=str(abs_path),
                status="failed",
                detail=f"拒绝写入目录路径（须为具体文件）: {rel}",
            )
        if abs_path.exists() and abs_path.is_dir():
            return ApplyItem(
                target_path=rel,
                abs_path=str(abs_path),
                status="failed",
                detail=f"目标已是目录，无法写文件: {rel}",
            )
        if dry_run:
            return ApplyItem(
                target_path=rel,
                abs_path=str(abs_path),
                status="skipped",
                detail="dry_run",
            )

        bak_rel = backup_dir / rel
        bak_rel.parent.mkdir(parents=True, exist_ok=True)
        if abs_path.exists():
            shutil.copy2(abs_path, bak_rel)
            backup_path = str(bak_rel)
        else:
            marker = Path(str(bak_rel) + ".deleted")
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("", encoding="utf-8")
            backup_path = str(marker)

        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(diff.code, encoding="utf-8")
        return ApplyItem(
            target_path=rel,
            abs_path=str(abs_path),
            status="written",
            backup_path=backup_path,
        )

    def _normalize_rel(self, target_path: str) -> Optional[str]:
        if not target_path or target_path.startswith("/") or "\\" in target_path[:2]:
            # 拒绝绝对路径（Windows 盘符简单处理）
            if Path(target_path).is_absolute():
                return None
        raw = target_path.replace("\\", "/").lstrip("./")
        if not raw or ".." in Path(raw).parts:
            return None
        candidate = (self.workspace_root / raw).resolve()
        try:
            candidate.relative_to(self.workspace_root)
        except ValueError:
            return None
        return str(Path(raw))

    def _allowed(self, rel: str) -> bool:
        rel_posix = rel.replace("\\", "/")
        for pattern in self.allowed_globs:
            if fnmatch.fnmatch(rel_posix, pattern):
                return True
            # 兼容前缀式：src/** 匹配 src/foo.py
            if pattern.endswith("/**"):
                prefix = pattern[:-3]
                if rel_posix == prefix or rel_posix.startswith(prefix + "/"):
                    return True
        return False


def collect_py_paths(diffs: Iterable[UnitDiff], workspace_root: Path) -> List[Path]:
    paths: List[Path] = []
    for d in diffs:
        if d.target_path.endswith(".py"):
            paths.append((workspace_root / d.target_path).resolve())
    return paths
