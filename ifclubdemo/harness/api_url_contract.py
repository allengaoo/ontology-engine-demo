"""
api_url_contract — API URL 规范化契约（前后端共用一条规则）

规范（单一真相）：
1) 全局前缀只定义一次：API_V1_PREFIX = "/api/v1"
2) 后端 router 只声明资源段：prefix="/rooms" / "/bookings"（禁止再写 /api/v1）
3) main 挂载时统一加前缀：include_router(..., prefix=API_V1_PREFIX)
4) 前端 apiBase === API_V1_PREFIX；调用只写 "/rooms"、"/bookings"

违反时典型症状：浏览器打到 /api/v1/api/v1/rooms → 404 →「加载失败：请确认后端 /api/v1 可用」
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class UrlContractViolation:
    rule_id: str
    path: str
    detail: str


@dataclass
class UrlContractResult:
    ok: bool
    violations: List[UrlContractViolation] = field(default_factory=list)
    checks_run: int = 0

    def summary(self) -> str:
        if self.ok:
            return f"API-URL-CONTRACT PASS ({self.checks_run} checks)"
        parts = [f"{v.rule_id}:{v.path}: {v.detail}" for v in self.violations[:8]]
        return "API-URL-CONTRACT FAIL: " + "; ".join(parts)


API_V1 = "/api/v1"


def check_api_url_contract(root: Path) -> UrlContractResult:
    root = Path(root).resolve()
    violations: List[UrlContractViolation] = []
    checks = 0

    # 1) 后端单一常量
    checks += 1
    config = root / "backend/src/meeting_order/config.py"
    if not config.is_file():
        violations.append(
            UrlContractViolation(
                "API-URL-PREFIX-CONST",
                "backend/src/meeting_order/config.py",
                "缺少 config.py；须定义 API_V1_PREFIX = \"/api/v1\"",
            )
        )
    else:
        text = config.read_text(encoding="utf-8", errors="replace")
        if 'API_V1_PREFIX' not in text or f'"{API_V1}"' not in text and f"'{API_V1}'" not in text:
            violations.append(
                UrlContractViolation(
                    "API-URL-PREFIX-CONST",
                    "backend/src/meeting_order/config.py",
                    f'须定义 API_V1_PREFIX = "{API_V1}"（全局唯一前缀）',
                )
            )

    # 2) main 用常量挂载，禁止资源 router 自己带 /api/v1
    checks += 1
    main = root / "backend/src/meeting_order/main.py"
    if main.is_file():
        mtext = main.read_text(encoding="utf-8", errors="replace")
        if "API_V1_PREFIX" not in mtext:
            violations.append(
                UrlContractViolation(
                    "API-URL-MAIN-MOUNT",
                    "backend/src/meeting_order/main.py",
                    "include_router 须使用 API_V1_PREFIX，禁止魔法字符串散落",
                )
            )
        if re.search(r'APIRouter\(\s*prefix\s*=\s*["\']/api/v1', mtext):
            violations.append(
                UrlContractViolation(
                    "API-URL-MAIN-MOUNT",
                    "backend/src/meeting_order/main.py",
                    "main 内不要再建带 /api/v1 的 APIRouter；前缀只在 include_router",
                )
            )

    for rel, resource in (
        ("backend/src/meeting_order/api/rooms.py", "/rooms"),
        ("backend/src/meeting_order/api/bookings.py", "/bookings"),
    ):
        checks += 1
        path = root / rel
        if not path.is_file():
            violations.append(
                UrlContractViolation("API-URL-ROUTER-RESOURCE", rel, "文件不存在")
            )
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "/api/v1" in text:
            violations.append(
                UrlContractViolation(
                    "API-URL-ROUTER-RESOURCE",
                    rel,
                    f"router 禁止含 /api/v1；只声明资源段 prefix=\"{resource}\"",
                )
            )
        if f'prefix="{resource}"' not in text and f"prefix='{resource}'" not in text:
            # 宽松：允许 prefix="/rooms" 出现
            if "APIRouter" in text and resource not in text:
                violations.append(
                    UrlContractViolation(
                        "API-URL-ROUTER-RESOURCE",
                        rel,
                        f'APIRouter 须 prefix="{resource}"',
                    )
                )

    # 3) 前端 apiBase 对齐同一前缀；调用侧禁止再拼 /api/v1
    checks += 1
    client = root / "frontend/src/api/client.ts"
    if client.is_file():
        ctext = client.read_text(encoding="utf-8", errors="replace")
        if f'apiBase = "{API_V1}"' not in ctext and f"apiBase = '{API_V1}'" not in ctext:
            violations.append(
                UrlContractViolation(
                    "API-URL-FE-BASE",
                    "frontend/src/api/client.ts",
                    f'apiBase 必须等于后端 API_V1_PREFIX（"{API_V1}"）',
                )
            )
        if "joinApiPath" not in ctext:
            violations.append(
                UrlContractViolation(
                    "API-URL-FE-BASE",
                    "frontend/src/api/client.ts",
                    "须提供 joinApiPath，防止调用方误传完整 URL 导致双写",
                )
            )

    checks += 1
    page = root / "frontend/src/pages/BookingPage.tsx"
    if page.is_file():
        ptext = page.read_text(encoding="utf-8", errors="replace")
        for bad in (
            'apiGet("/api/v1/',
            "apiGet('/api/v1/",
            'apiPost("/api/v1/',
            "apiPost('/api/v1/",
        ):
            if bad in ptext:
                violations.append(
                    UrlContractViolation(
                        "API-URL-FE-CALL",
                        "frontend/src/pages/BookingPage.tsx",
                        "调用只写资源路径 /rooms、/bookings；前缀由 apiBase/API_V1_PREFIX 提供",
                    )
                )
                break

    return UrlContractResult(
        ok=not violations, violations=violations, checks_run=checks
    )
