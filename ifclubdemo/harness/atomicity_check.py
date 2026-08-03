"""
atomicity_check — StructurePlan 原子性校验（Phase 8 Harness）

Harness 侧确定性检查：路径白名单、禁止路径、依赖环、Unit 粒度。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Set

from agents.structure_plan import StructurePlan
from harness.freeze_state import is_frozen


class CheckOutcome(str, Enum):
    PASS = "pass"
    FAIL_STRUCT = "fail_struct"


@dataclass
class AtomicityResult:
    outcome: CheckOutcome
    rule_id: str = ""
    detail: str = ""
    violations: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.outcome == CheckOutcome.PASS


DEFAULT_ALLOWED_PREFIXES = (
    "src/",
    "backend/",
    "frontend/src/",
    "frontend/public/",
    "frontend/index.html",  # 精确文件：startswith 仍可匹配整路径
    "tests/",
    "docs/",
    "data/",
    "acceptance/",
)

# 明确禁止：历史上 BSA 常踩的坑
FORBIDDEN_EXACT = frozenset(
    {
        "backend/src/main.py",
        "backend/src/meeting_order/models.py",  # 与 models/ 包冲突
    }
)

FORBIDDEN_SUBSTRINGS = (
    "backend.src.",
    "src/purchasing/",
    "tests/purchasing/",
    "/forbidden/",
)

# 当工作区是会议应用时，禁止丢掉包名的路径
MEETING_FORBIDDEN_SUBSTRINGS = (
    "backend/src/repositories/",  # 必须是 backend/src/meeting_order/repositories/
    "backend/src/models/",
    "backend/src/services/",
    "backend/src/api/",
    "backend/src/domain/",
    # 正确文件名是 sqlite_repo.py；禁止另起 sqlite.py 造成双实现
    "meeting_order/repositories/sqlite.py",
)


class AtomicityCheck:
    """StructurePlan 原子性与路径白名单校验。"""

    def __init__(
        self,
        allowed_prefixes: Optional[tuple] = None,
        *,
        frozen_prefixes: Optional[List[str]] = None,
        extra_forbidden_substrings: Optional[tuple] = None,
    ):
        self.allowed_prefixes = allowed_prefixes or DEFAULT_ALLOWED_PREFIXES
        self.frozen_prefixes: List[str] = list(frozen_prefixes or [])
        self.extra_forbidden_substrings: tuple = tuple(extra_forbidden_substrings or ())

    def set_frozen_prefixes(self, prefixes: Optional[List[str]]) -> None:
        self.frozen_prefixes = list(prefixes or [])

    def check(self, plan: StructurePlan) -> AtomicityResult:
        violations: List[str] = []

        if not plan.units:
            violations.append("StructurePlan 无 Unit")

        unit_ids = {u.unit_id for u in self._iter_units(plan)}
        seen_paths: Set[str] = set()
        banned = FORBIDDEN_SUBSTRINGS + self.extra_forbidden_substrings
        for u in self._iter_units(plan):
            path = (u.target_path or "").replace("\\", "/").lstrip("./")
            if not path:
                violations.append(f"Unit {u.unit_id} 缺少 target_path")
                continue
            name = path.rstrip("/").rsplit("/", 1)[-1]
            if path.endswith("/") or "." not in name:
                violations.append(
                    f"Unit {u.unit_id} target_path 必须是文件而非目录: {path}"
                )
            if is_frozen(path, self.frozen_prefixes):
                violations.append(
                    f"Unit {u.unit_id} 目标已 freeze，禁止修改: {path}"
                )
            if path in FORBIDDEN_EXACT:
                violations.append(f"Unit {u.unit_id} 禁止路径 {path}")
            for frag in banned:
                if frag in path:
                    violations.append(
                        f"Unit {u.unit_id} 路径含禁止片段 {frag!r}: {path}"
                    )
            if not any(path.startswith(p) for p in self.allowed_prefixes):
                violations.append(
                    f"Unit {u.unit_id} 路径 {path} 不在白名单 {self.allowed_prefixes}"
                )
            if path in seen_paths:
                violations.append(f"重复 target_path: {path}")
            seen_paths.add(path)
            for dep in u.depends_on:
                if dep not in unit_ids:
                    violations.append(f"Unit {u.unit_id} 依赖未知 Unit {dep}")

        cycle = self._detect_cycle(plan)
        if cycle:
            violations.append(f"Unit 依赖环：{' → '.join(cycle)}")

        if violations:
            return AtomicityResult(
                outcome=CheckOutcome.FAIL_STRUCT,
                rule_id="STRUCT-001",
                detail=violations[0],
                violations=violations,
            )
        return AtomicityResult(outcome=CheckOutcome.PASS)

    @staticmethod
    def _iter_units(plan: StructurePlan):
        return plan.units

    def _detect_cycle(self, plan: StructurePlan) -> Optional[List[str]]:
        graph = {u.unit_id: u.depends_on for u in plan.units}
        visited: Set[str] = set()
        stack: Set[str] = set()
        path: List[str] = []

        def dfs(node: str) -> Optional[List[str]]:
            if node in stack:
                idx = path.index(node)
                return path[idx:] + [node]
            if node in visited:
                return None
            visited.add(node)
            stack.add(node)
            path.append(node)
            for dep in graph.get(node, []):
                cyc = dfs(dep)
                if cyc:
                    return cyc
            path.pop()
            stack.remove(node)
            return None

        for uid in graph:
            cyc = dfs(uid)
            if cyc:
                return cyc
        return None
