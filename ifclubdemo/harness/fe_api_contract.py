"""
fe_api_contract — 前端↔后端接线契约（小模型友好、确定性、无浏览器）

覆盖三类「业务可用性」缺口（相对纯 API 功能测试）：
1) 列表数据是否接到控件（下拉/列表）
2) 时间控件是否用浏览器原生 datetime-local
3) 写成功后是否再拉列表刷新

可复用到其他 CRUD 小应用：把 REQUIRED_PATTERNS 换成对应路径即可。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple


@dataclass
class FeContractViolation:
    rule_id: str
    path: str
    detail: str


@dataclass
class FeContractResult:
    ok: bool
    violations: List[FeContractViolation] = field(default_factory=list)
    checks_run: int = 0

    def summary(self) -> str:
        if self.ok:
            return f"FE-API-CONTRACT PASS ({self.checks_run} checks)"
        parts = [f"{v.rule_id}:{v.path}: {v.detail}" for v in self.violations[:8]]
        return "FE-API-CONTRACT FAIL: " + "; ".join(parts)


# (rule_id, relative path, must-contain substring list, human tip)
MeetingFePattern = Tuple[str, str, Sequence[str], str]

# (rule_id, relative path, forbidden substrings, tip)
MeetingFeForbid = Tuple[str, str, Sequence[str], str]

MEETING_FE_PATTERNS: List[MeetingFePattern] = [
    (
        "FE-WIRE-ROOMS-PROP",
        "frontend/src/components/BookingForm.tsx",
        ("rooms", "option", "is_active"),
        "BookingForm 必须接收 rooms 并用 <option> 渲染启用会议室",
    ),
    (
        "FE-WIRE-DATETIME",
        "frontend/src/components/BookingForm.tsx",
        ('type="datetime-local"', "start_at", "end_at"),
        "开始/结束时间必须用 type=datetime-local，禁止纯文本 placeholder 时间",
    ),
    (
        "FE-WIRE-SUBMIT",
        "frontend/src/components/BookingForm.tsx",
        ("onSubmit", "FormData", "preventDefault"),
        "表单必须 FormData 收集字段并调用 props.onSubmit，禁止空 preventDefault",
    ),
    (
        "FE-WIRE-PAGE-PASS-ROOMS",
        "frontend/src/pages/BookingPage.tsx",
        ("BookingForm", "rooms=", "onSubmit"),
        "BookingPage 必须把 rooms 与 onSubmit 传给 BookingForm",
    ),
    (
        "FE-WIRE-LOAD-API",
        "frontend/src/pages/BookingPage.tsx",
        ('"/rooms"', '"/bookings"'),
        "页面加载须 apiGet(\"/rooms\") 与 apiGet(\"/bookings\")（不要再写 /api/v1 前缀）",
    ),
    (
        "FE-WIRE-REFRESH",
        "frontend/src/pages/BookingPage.tsx",
        ('"/bookings"', "setBookings"),
        "提交成功后必须重新拉取 bookings 并 setBookings，列表才会更新",
    ),
    (
        "FE-WIRE-API-CLIENT",
        "frontend/src/api/client.ts",
        ("/api/v1", "apiGet", "apiPost", "joinApiPath"),
        "统一 apiBase=/api/v1 + joinApiPath，防止双写 /api/v1/api/v1/...",
    ),
    (
        "FE-WIRE-VITE-PROXY",
        "frontend/vite.config.ts",
        ('"/api"', "8000"),
        "vite 必须把 /api 代理到后端 8000，否则浏览器直连失败",
    ),
]

MEETING_FE_FORBID: List[MeetingFeForbid] = [
    (
        "FE-WIRE-NO-DOUBLE-PREFIX",
        "frontend/src/pages/BookingPage.tsx",
        (
            'apiGet("/api/v1/',
            "apiGet('/api/v1/",
            'apiPost("/api/v1/',
            "apiPost('/api/v1/",
            'fetch("/api/v1/api/v1/',
            "fetch('/api/v1/api/v1/",
        ),
        "apiBase 已是 /api/v1 时禁止再传 /api/v1/rooms；应写 /rooms、/bookings。"
        "否则浏览器请求 /api/v1/api/v1/rooms → 404，页面显示加载失败。",
    ),
]


def check_fe_api_contract(
    root: Path,
    *,
    patterns: Optional[List[MeetingFePattern]] = None,
    forbids: Optional[List[MeetingFeForbid]] = None,
) -> FeContractResult:
    root = Path(root).resolve()
    patterns = list(patterns or MEETING_FE_PATTERNS)
    forbids = list(forbids or MEETING_FE_FORBID)
    violations: List[FeContractViolation] = []
    checks = 0

    for rule_id, rel, needles, tip in patterns:
        checks += 1
        path = root / rel
        if not path.is_file():
            violations.append(
                FeContractViolation(rule_id, rel, f"文件不存在；{tip}")
            )
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            violations.append(
                FeContractViolation(rule_id, rel, f"无法读取: {exc}")
            )
            continue
        missing = [n for n in needles if n not in text]
        if missing:
            violations.append(
                FeContractViolation(
                    rule_id,
                    rel,
                    f"缺少 {missing}；{tip}",
                )
            )

    for rule_id, rel, banned, tip in forbids:
        checks += 1
        path = root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = [b for b in banned if b in text]
        if hits:
            violations.append(
                FeContractViolation(
                    rule_id,
                    rel,
                    f"禁止双写 API 前缀，发现 {hits}；{tip}",
                )
            )

    return FeContractResult(ok=not violations, violations=violations, checks_run=checks)
