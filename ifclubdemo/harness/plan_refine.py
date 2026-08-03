"""
plan_refine — BSA StructurePlan 细化（零 LLM）

1) 剔除已 freeze 路径上的 Unit（计划期剪枝，避免浪费 STRUCT replan）
2) 强制 Unit 数量上限（默认 2；可由 task.context[_max_units] 覆盖）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from agents.structure_plan import StructurePlan
from harness.freeze_state import is_frozen


@dataclass
class PlanRefineResult:
    plan: StructurePlan
    pruned_paths: List[str] = field(default_factory=list)
    ok: bool = True
    rule_id: str = ""
    detail: str = ""


def refine_structure_plan(
    plan: StructurePlan,
    *,
    frozen_prefixes: Optional[Sequence[str]] = None,
    max_units: int = 2,
) -> PlanRefineResult:
    frozen = list(frozen_prefixes or [])
    max_units = max(1, int(max_units or 2))

    kept = []
    pruned: List[str] = []
    for u in plan.units:
        path = (u.target_path or "").replace("\\", "/").lstrip("./")
        if frozen and is_frozen(path, frozen):
            pruned.append(path)
            continue
        kept.append(u)

    plan.units = kept
    result = PlanRefineResult(plan=plan, pruned_paths=pruned)

    if pruned:
        print(f"  [plan_refine] 已剔除 freeze Unit: {pruned}")

    if not plan.units:
        result.ok = False
        result.rule_id = "FREEZE-EMPTY"
        result.detail = (
            "StructurePlan 在剔除 freeze 路径后无剩余 Unit；"
            "请只规划未冻结文件，并只读 models/rules 签名"
        )
        return result

    bad_dirs = [
        (u.target_path or "").replace("\\", "/").lstrip("./")
        for u in plan.units
        if _looks_like_directory((u.target_path or "").replace("\\", "/").lstrip("./"))
    ]
    if bad_dirs:
        result.ok = False
        result.rule_id = "UNIT-FILE-PATH"
        result.detail = (
            "Unit.target_path 必须是具体文件（含扩展名），禁止目录："
            f"{bad_dirs}；例如用 room.py + booking.py，不要用 models/"
        )
        return result

    if len(plan.units) > max_units:
        paths = [u.target_path for u in plan.units]
        result.ok = False
        result.rule_id = "UNIT-BUDGET"
        result.detail = (
            f"Unit 数 {len(plan.units)} 超过上限 {max_units}；"
            f"请拆成更小 EP，每个 Unit 一个具体文件"
            f"（当前: {paths}）。本轮若要做 room+booking，恰好 2 个文件路径即可。"
        )
        return result

    return result


def _looks_like_directory(path: str) -> bool:
    if not path:
        return True
    if path.endswith("/"):
        return True
    name = path.rsplit("/", 1)[-1]
    # 无扩展名的末段视为目录（拒绝 models / api 这类伪 Unit）
    return "." not in name


def collect_upstream_signature_paths(
    target_path: str = "",
    *,
    app: str = "",
) -> List[str]:
    """CA / coordinator 注入用的上游只读路径。"""
    rel = (target_path or "").replace("\\", "/")
    app_name = (app or "").strip() or "meeting_order"

    base = [
        "backend/src/meeting_order/models/room.py",
        "backend/src/meeting_order/models/booking.py",
        "backend/src/meeting_order/models/__init__.py",
        "backend/src/meeting_order/domain/rules.py",
        "backend/src/meeting_order/repositories/base.py",
        "backend/src/meeting_order/repositories/factory.py",
        "backend/src/meeting_order/repositories/sqlite_repo.py",
        "backend/src/meeting_order/schemas/booking.py",
        "backend/src/meeting_order/config.py",
        "backend/src/meeting_order/db.py",
        "backend/src/meeting_order/main.py",
        "docs/meeting_schema.json",
        "data/seed_rooms.json",
    ]
    if "api/" in rel or "test_api" in rel or "services/" in rel:
        base.extend(
            [
                "backend/src/meeting_order/api/rooms.py",
                "backend/src/meeting_order/api/bookings.py",
                "backend/src/meeting_order/services/booking_service.py",
            ]
        )
    return base
