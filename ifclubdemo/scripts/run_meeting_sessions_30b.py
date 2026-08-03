#!/usr/bin/env python3
"""
会议室预订：Session A/B 各 10 轮，全程 qwen3-coder-30b-a3b-instruct 经 CLI/EP 生成。

对齐 scripts/run_twosession_rebuild.py：每轮点名文件 + max_units，禁止 stub/手写补齐。
白话意图来自 docs/meeting_session_prompts.md；任务句改成 30B 可执行的微步骤。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FORCE_MODEL = os.environ.get("DEMOCODE_FORCE_MODEL", "qwen3-coder-30b-a3b-instruct")
WS = ROOT / "workspace" / "meeting_order"

PATH_RULE = (
    "硬性约束：只改 meeting_order 路径（backend/src/meeting_order/**、tests/meeting_order/**、"
    "frontend/src/**、docs/**、data/**）；禁止臆造其他包路径。"
)

SIG_HINT = (
    "对齐现有脚手架签名，禁止发明新入口："
    "config 含 DB_BACKEND/DB_PATH/MYSQL_DSN 与 API_V1_PREFIX='/api/v1'（不要 settings/DB_TYPE）；"
    "URL 规范：router 只写 /rooms|/bookings；main 用 prefix=API_V1_PREFIX 挂载；"
    "前端 apiBase 等于 API_V1_PREFIX，调用只写 /rooms|/bookings（禁止双写 /api/v1）；"
    "factory 必须 init_db+seed_rooms_if_empty 与 get_repository()；"
    "Room(id,name,capacity,is_active)；Booking(id,room_id,title,booker,start_at,end_at)；"
    "种子读 data/seed_rooms.json（含 capacity）；"
    "协议只在 repositories/base.py：class MeetingRepository(Protocol)，方法含 "
    "list_rooms/get_room/list_bookings/create_booking；"
    "实现类名必须 SqliteRepository（单类），禁止 BaseRoomRepository/"
    "BaseBookingRepository/repositories.booking；"
    "SqliteRepository 内必须 `import meeting_order.config as config` 且 "
    "self.db_path=config.DB_PATH（禁止 from config import DB_PATH 导致 monkeypatch 失效）；"
    "API POST 须 try/except ValueError→HTTP 409 detail="
    '{"code":"BOOKING_CONFLICT","message":...}（包住全部检查，不只包 create）。'
)

UNIT_HINT = (
    "本轮硬规则（小模型）：BSA 只规划 1 个 Unit；只改下方点名的那一个文件；"
    "改前先读该文件现有内容与上游签名；每个 import 必须能在依赖文件中找到；"
    "函数/变量 snake_case，类 PascalCase；单文件 ≤220 行；depends_on 必须 []。"
)


def _tee(log_path: Path):
    class Tee:
        def __init__(self, path: Path):
            self.f = path.open("a", encoding="utf-8")
            self.stdout = sys.stdout

        def write(self, s):
            self.stdout.write(s)
            self.f.write(s)
            self.f.flush()

        def flush(self):
            self.stdout.flush()
            self.f.flush()

    sys.stdout = Tee(log_path)  # type: ignore
    sys.stderr = sys.stdout  # type: ignore


def _restore_distilled_memories(archive: Path) -> int:
    """从归档工作区迁回会议域沉淀记忆（CN-MEETING / ANTI-MEETING），验证经验可迁移。"""
    src_dom = archive / ".ontology_agent" / "memory" / "DOMAIN"
    dst_dom = WS / ".ontology_agent" / "memory" / "DOMAIN"
    if not src_dom.is_dir():
        print("  [memory] no DOMAIN memories in archive")
        return 0
    dst_dom.mkdir(parents=True, exist_ok=True)
    n = 0
    patterns = (
        "CN-MEETING-*.md",
        "ANTI-MEETING-*.md",
        "PAT-MEETING-*.md",
        "CN-MEETING-FAIL-*.md",
        "CN-MEETING-LOOP-*.md",
        "CN-MEETING-SQLITE-IMPL.md",
        "ANTI-MEETING-ASSERT-*.md",
    )
    for pat in patterns:
        for p in src_dom.glob(pat):
            shutil.copy2(p, dst_dom / p.name)
            n += 1
            print(f"  [memory] restore {p.name}")
    # 可选：迁回带 meeting 关键词的 ANTI-EP（失败教训）
    for p in src_dom.glob("ANTI-EP-*.md"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "meeting_order" in text:
            shutil.copy2(p, dst_dom / p.name)
            n += 1
            print(f"  [memory] restore {p.name} (meeting-related ANTI-EP)")
    return n


def reset_workspace() -> None:
    archive: Path | None = None
    preserve = os.environ.get("PRESERVE_DISTILLED_MEMORY", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if WS.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        archive = ROOT / "legacy" / f"meeting_order-pre30b-{stamp}"
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(WS), str(archive))
        print(f"archived previous workspace → {archive}")

    subprocess.run(
        [sys.executable, "cli.py", "init-app", "meeting_order"],
        cwd=ROOT,
        check=True,
    )
    for cmd, rel in (
        ("inject", "docs/business_brief.md"),
        ("inject-arch", "docs/architecture_brief.md"),
    ):
        subprocess.run(
            [
                sys.executable,
                "cli.py",
                cmd,
                str(WS / rel),
                "--workspace",
                str(WS),
            ],
            cwd=ROOT,
            check=False,
        )
    for name in (
        "meeting_business_scenario.md",
        "meeting_session_prompts.md",
        "meeting_test_plan.md",
    ):
        src = ROOT / "docs" / name
        if src.exists():
            shutil.copy2(src, WS / "docs" / name)

    if preserve and archive is not None:
        print("\n== restore distilled memories from prior run ==")
        n = _restore_distilled_memories(archive)
        print(f"  [memory] restored {n} files")
        # 标记本轮是「带经验干净重建」
        meta = WS / ".ontology_agent" / "rebuild_with_memory.json"
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(
            json.dumps(
                {
                    "mode": "clean_rebuild_with_distilled_memory",
                    "from_archive": str(archive),
                    "restored_count": n,
                    "at": datetime.now().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def build_rounds() -> list[dict]:
    """20 轮：全部默认 max_units=1（单文件微步骤），适配 30B 短上下文。"""
    common = f"{PATH_RULE} {UNIT_HINT}"
    s1 = [
        {
            "label": "A1-scope",
            "gate_layer": "domain",
            "max_units": 1,
            "skip_pytest": True,
            "task": (
                f"{common} 这一轮只新建 docs/scope.md：用大白话写我们要做的这个小演示"
                "——大家订会议室常遇到的烦心事（时间撞车、房间停用了、报错没原因），"
                "做成什么样算成功，以及我们故意不做的那些（审批、登录、通知、按人数卡容量、复杂日历）。"
                "用三句话分别说清「要做的」「不做的」「成功的样子」。"
            ),
        },
        {
            "label": "A2-rules-brief",
            "gate_layer": "domain",
            "max_units": 1,
            "skip_pytest": True,
            "task": (
                f"{common} 这一轮只新建 docs/rules_brief.md：用大白话把订会议室的几条规矩写下来"
                "——结束时间得比开始时间晚；同一个房间的时间不能重叠，但前后紧挨着可以；"
                "只能订还在用的房间；撞车了要拒绝并告诉原因；以系统检查为准。"
                "再补一句「本演示不做的事」。"
            ),
        },
        {
            "label": "A3-repo-protocol",
            "gate_layer": "domain",
            "max_units": 1,
            "skip_pytest": True,
            "task": (
                f"{common} {SIG_HINT} 这一轮只改 backend/src/meeting_order/repositories/base.py："
                "给「怎么存取会议室和预订」定一个统一入口，列出四件事——"
                "查所有会议室、查单个会议室、查所有预订、新建一条预订。"
                "先只写接口约定，不写真正的存取实现。"
            ),
        },
        {
            "label": "A4-sqlite-rooms",
            "gate_layer": "domain",
            "max_units": 1,
            "skip_pytest": True,
            "task": (
                f"{common} {SIG_HINT} 这一轮只改 backend/src/meeting_order/repositories/sqlite_repo.py："
                "用 SQLite 把会议室存起来——建一张房间表，"
                "第一次启动时把种子会议室填进去（至少两个可用、一个停用），"
                "再提供列出所有房间、查单个房间的能力。"
            ),
        },
        {
            "label": "A5-factory",
            "gate_layer": "domain",
            "max_units": 1,
            "skip_pytest": True,
            "task": (
                f"{common} {SIG_HINT} 这一轮只改 backend/src/meeting_order/repositories/factory.py："
                "做一个统一入口来初始化数据库、拿到存取对象。"
                "初始化时一定要把种子会议室填好，不然页面打开房间列表是空的；"
                "再提供一个方法拿到那个存取对象。"
            ),
        },
        {
            "label": "A6-api-rooms",
            "gate_layer": "api",
            "max_units": 1,
            "skip_pytest": True,
            "task": (
                f"{common} {SIG_HINT} 这一轮只改 backend/src/meeting_order/api/rooms.py："
                "做一个接口让前端能拿到会议室列表，"
                "每间房要能看到房间号、名字、容量、是否还在用。"
            ),
        },
        {
            "label": "A7-domain-rules",
            "gate_layer": "domain",
            "max_units": 1,
            "skip_pytest": True,
            "task": (
                f"{common} {SIG_HINT} 这一轮只改 backend/src/meeting_order/domain/rules.py："
                "把订会议室的规矩写成不碰数据库的纯函数——"
                "时间合不合法、会不会和已有预订撞车、房间是不是还能用。"
                "出错时用大白话说原因。"
            ),
        },
        {
            "label": "A8-sqlite-bookings",
            "gate_layer": "domain",
            "max_units": 1,
            "skip_pytest": True,
            "task": (
                f"{common} {SIG_HINT} 这一轮只改 backend/src/meeting_order/repositories/sqlite_repo.py："
                "在刚才的存取对象上再补上「预订」的存取——建一张预订表，"
                "能列出所有预订、能新建一条预订。"
                "这一步先不查撞车，撞车交给后面那一步。"
            ),
        },
        {
            "label": "A9-booking-service",
            "gate_layer": "api",
            "max_units": 1,
            "skip_pytest": True,
            "task": (
                f"{common} {SIG_HINT} 这一轮只改 backend/src/meeting_order/services/booking_service.py："
                "把订会议室的步骤串起来——先查房间在不在、还能不能用、时间对不对、"
                "会不会和已有预订撞车，都没问题再存进去。"
                "有问题就抛出来，让接口去变成 409。"
            ),
        },
        {
            "label": "A10-api-bookings",
            "gate_layer": "api",
            "max_units": 1,
            "skip_pytest": True,
            "task": (
                f"{common} {SIG_HINT} 这一轮只改 backend/src/meeting_order/api/bookings.py："
                "做预订的对外接口——能列出预订；新建预订时把检查和保存一起包住，"
                "出问题就返回 409 和「撞车」的提示，别让错误变成 500。"
            ),
        },
    ]
    s2 = [
        {
            "label": "B1-layer-brief",
            "gate_layer": "domain",
            "max_units": 1,
            "skip_pytest": True,
            "task": (
                f"{common} 这一轮只新建/改 docs/layer_roles.md：用大白话说清楚"
                "页面、规矩检查、存取、对外接口各自该干什么活，别互相抢。"
            ),
        },
        {
            "label": "B2-dto",
            "gate_layer": "api",
            "max_units": 1,
            "skip_pytest": True,
            "task": (
                f"{common} {SIG_HINT} 这一轮只改 backend/src/meeting_order/schemas/booking.py："
                "把「新建预订」要传的字段定死——哪个房间、会议名、预订人、开始时间、结束时间。"
                "可以再补一个回传用的结构（带上编号）。字段名别乱改。"
            ),
        },
        {
            "label": "B3-test-rules",
            "gate_layer": "domain",
            "max_units": 1,
            "tests": "tests/meeting_order/test_rules.py",
            "task": (
                f"{common} {SIG_HINT} 这一轮只新建/改 tests/meeting_order/test_rules.py："
                "给规矩检查写测试——坏时间、撞车、首尾相接、停用房、不同房互不影响。"
                "测试要能跑过。这一步别改规矩本身，如果红了留给下一轮修。"
            ),
        },
        {
            "label": "B4-api-409",
            "gate_layer": "api",
            "max_units": 1,
            "skip_pytest": True,
            "task": (
                f"{common} {SIG_HINT} 这一轮只改 backend/src/meeting_order/api/bookings.py："
                "把新建预订接口的「撞车返回 409」做稳——检查和保存要一起包住，"
                "出错返回 409 和提示，别只包住保存那一步漏掉撞车检查。"
            ),
        },
        {
            "label": "B5-test-api",
            "gate_layer": "api",
            "max_units": 1,
            "tests": "tests/meeting_order",
            "task": (
                f"{common} {SIG_HINT} 这一轮优先改 tests/meeting_order/test_api.py："
                "给接口写测试——能拿到房间、合法预订能成功、撞车预订返回 409 加提示。"
                "如果打开房间列表是空的，就去改初始化那一步把种子房间填好。测试要能跑过。"
            ),
        },
        {
            "label": "B6-fe-booking-page",
            "gate_layer": "frontend",
            "max_units": 1,
            "tests": "",
            "vite_build": True,
            "task": (
                f"{common} 这一轮只改 frontend/src/components/BookingForm.tsx："
                "做预订表单——能选房间（只显示可用的）、选开始和结束时间、填好点提交。"
                "别在页面自己判断撞车，撞车交给后端。"
            ),
        },
        {
            "label": "B7-fe-lists-errors",
            "gate_layer": "frontend",
            "max_units": 1,
            "tests": "",
            "vite_build": True,
            "task": (
                f"{common} 这一轮只改 frontend/src/pages/BookingPage.tsx："
                "做主页面——打开时去拿会议室和预订列表、显示表单、"
                "提交成功后刷新列表、撞车时把后端返回的提示显示出来。"
            ),
        },
        {
            "label": "B8-fe-rules-panel",
            "gate_layer": "frontend",
            "max_units": 1,
            "tests": "",
            "vite_build": True,
            "task": (
                f"{common} 这一轮只改 frontend/src/components/RulesPanel.tsx："
                "做一个小区块放订会议室的规矩说明，照着之前写的规矩文档来，"
                "再加两三句怎么操作。别动后端，也别改表单和主页面的接线。"
            ),
        },
        {
            "label": "B9-repair",
            "gate_layer": "api",
            "max_units": 1,
            "tests": "tests/meeting_order",
            "task": (
                f"{common} {SIG_HINT} 这一轮是 Repair：看现在哪里还红，"
                "只改一个跟当前失败最相关的文件，让测试全部跑过。"
            ),
        },
        {
            "label": "B10-final",
            "gate_layer": "api",
            "max_units": 1,
            "tests": "tests/meeting_order",
            "vite_build": True,
            "task": (
                f"{common} {SIG_HINT} 这一轮是 Final：只新增 docs/demo_checklist.md，"
                "用大白话写演示步骤和验收清单。如果测试和前端构建都已经绿了，就别动代码；"
                "如果还红，允许再改一个代码文件让它全绿。"
            ),
        },
    ]
    rounds: list[dict] = []
    for r in s1:
        r["session"] = "session-A"
        rounds.append(r)
    for r in s2:
        r["session"] = "session-B"
        rounds.append(r)
    start_from = os.environ.get("START_FROM", "").strip()
    if start_from:
        labels = [r["label"] for r in rounds]
        if start_from not in labels:
            raise SystemExit(f"START_FROM={start_from} not in {labels}")
        rounds = rounds[labels.index(start_from) :]
    assert len(rounds) >= 1
    return rounds


def _recent_anti_hint(ws: Path, limit: int = 5) -> str:
    root = ws / ".ontology_agent" / "memory"
    if not root.exists():
        return ""
    files = sorted(
        list(root.rglob("ANTI-EP-*.md"))
        + list(root.rglob("ANTI-MEETING-*.md"))
        + list(root.rglob("CN-MEETING-FAIL-*.md")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    chunks = []
    for p in files[:limit]:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        title = ""
        how = []
        in_how = False
        for line in text.splitlines():
            if line.startswith("title:"):
                title = line.split(":", 1)[1].strip()
            if line.strip() == "## HOW":
                in_how = True
                continue
            if in_how:
                if line.startswith("## "):
                    break
                if line.strip():
                    how.append(line.strip())
        chunks.append(f"### {p.stem}\n{title}\n" + "\n".join(how[:10]))
    return "\n\n".join(chunks)


def _error_fingerprint(text: str) -> str:
    import hashlib
    import re

    keys = []
    for pat in (
        r"No module named '([^']+)'",
        r"cannot import name '([^']+)'",
        r"ModuleNotFoundError: ([^\n]+)",
        r"ImportError: ([^\n]+)",
        r"TypeError: ([^\n]+)",
        r"JSONDecodeError: ([^\n]+)",
        r"IMPORT-CROSS-APP[^\n]*",
        r"AssertionError: ([^\n]+)",
        r"E   ([^\n]+)",
    ):
        keys.extend(re.findall(pat, text)[:3])
    raw = "|".join(keys) if keys else text[:240]
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:12]


def _collect_failure_text(ws: Path, ep_result=None) -> str:
    chunks: list[str] = []
    fb = ws / ".ontology_agent" / "last_verify.json"
    if fb.exists():
        chunks.append(fb.read_text(encoding="utf-8", errors="replace"))
    if ep_result is not None:
        chunks.append(getattr(ep_result, "summary", lambda: "")() or "")
        for t in getattr(ep_result, "turns", []) or []:
            chunks.append(f"{getattr(t, 'rule_id', '')} {getattr(t, 'outcome', '')}")
    return "\n".join(chunks)


def distill_failure_to_memory(
    ws: Path, *, label: str, fail_text: str, attempt: int
) -> dict:
    """失败即时沉淀为 ANTI + Constraint，供下一轮 30B 强制避开。"""
    import re
    from datetime import datetime as _dt

    mem = ws / ".ontology_agent" / "memory" / "DOMAIN"
    mem.mkdir(parents=True, exist_ok=True)
    fp = _error_fingerprint(fail_text)
    stamp = _dt.utcnow().strftime("%H%M%S")
    tip = ""
    for line in fail_text.splitlines():
        if any(
            k in line
            for k in (
                "ModuleNotFoundError",
                "ImportError",
                "TypeError",
                "JSONDecodeError",
                "IMPORT-CROSS",
                "AssertionError",
                "E   ",
            )
        ):
            tip = line.strip()[:160]
            break
    if not tip:
        tip = fail_text.strip().splitlines()[-1][:160] if fail_text.strip() else "unknown"

    # 规则化修复路径
    if any(
        s in fail_text
        for s in (
            "BaseRoomRepository",
            "BaseBookingRepository",
            "BaseRepository",
            "SQLiteRoomRepository",
            "SYMBOL-FORBIDDEN",
        )
    ):
        fix = (
            "只用 MeetingRepository（base.py Protocol）+ SqliteRepository 单类；"
            "禁止 BaseRoom/BaseBooking/BaseRepository 拆分；factory 返回 SqliteRepository()"
        )
        cn = "仓储协议名必须是 MeetingRepository，实现类必须是 SqliteRepository"
    elif "IMPORT-RESOLVE" in fail_text:
        fix = "删除无法解析的 import；只引用已存在的 meeting_order 模块文件"
        cn = "import 必须指向磁盘已有模块"
    elif "repositories.booking" in fail_text or "repositories.room" in fail_text:
        fix = "禁止 invent repositories.booking / room；只用 base+factory+sqlite_repo"
        cn = "禁止虚构 repositories.booking 或 repositories.room 模块"
    elif "SqliteRepository" in fail_text and "positional" in fail_text:
        fix = "SqliteRepository() 无参；不要 SqliteRepository(DB_PATH)"
        cn = "SqliteRepository 构造器无参，DB_PATH 在类内读 config"
    elif "JSONDecodeError" in fail_text or "seed_rooms" in fail_text:
        fix = "seed_rooms.json 必须合法 JSON；路径用 config.ROOT/'data'/'seed_rooms.json'"
        cn = "种子文件必须是合法 JSON 数组且用 ROOT 绝对路径读取"
    elif "backend/src/repositories/" in fail_text:
        fix = "路径必须 backend/src/meeting_order/repositories/，禁止丢掉包名"
        cn = "禁止写入 backend/src/repositories/（缺 meeting_order 包名）"
    elif "ValueError" in fail_text and (
        "bookings.py" in fail_text or "check_no_overlap" in fail_text or "409" in fail_text
    ):
        fix = (
            "只改 backend/src/meeting_order/api/bookings.py："
            "用 try/except ValueError 转 HTTPException(409, "
            'detail={"code":"BOOKING_CONFLICT","message": str(e)})；'
            "优先调用 BookingService.create_booking；禁止 ValueError 冒泡 500"
        )
        cn = "API 预订入口必须把 domain ValueError 转成 HTTP 409 BOOKING_CONFLICT"
    elif (
        "assert 0 ==" in fail_text
        or "0 >= 2" in fail_text
        or ("len(rooms)" in fail_text and "0" in fail_text)
    ):
        fix = (
            "只改 repositories/factory.py：init_db 必须 "
            "SqliteRepository(); repo.init_db(); repo.seed_rooms_if_empty()"
        )
        cn = "factory.init_db 必须种子会议室，禁止只建空表"
    else:
        fix = "先读 base.py/factory.py/sqlite_repo.py 签名再改；每轮 1 文件；禁止扩大范围"
        cn = f"轮次 {label} 失败后必须先避开已沉淀 ANTI 再改代码"

    anti_id = f"ANTI-MEETING-{fp}-{stamp}"
    cn_id = f"CN-MEETING-FAIL-{fp}"
    tip_title = tip[:60].replace('"', "'")
    cn_title = cn[:80].replace('"', "'")
    anti_body = f"""---
id: {anti_id}
object_type: AntiPatternMemory
title: "{label} attempt{attempt}: {tip_title}"
layer: DOMAIN
tier: hot
tags:
- meeting_order
- ep-fail
- distilled
- gc-protect
confidence: 0.96
schema_version: 2
about_concepts:
- meeting_order
- booking
- ep-fail
status: active
domain: domain
severity: high
fix_path: {fix}
gc_protect: true
fingerprint: {fp}
---

## HOW

- 轮次: `{label}` attempt={attempt}
- 指纹: `{fp}`
- 关键错误: {tip}
- **必须先做**: {fix}
- 禁止重复尝试同一错误写法；若仍失败，缩小为 1 文件并贴齐现有签名

## 信号

```
{fail_text[:1800]}
```

## WHEN

meeting_order 任意 EP / Repair；CodingAgent 必须先读本条再改代码。
"""
    cn_body = f"""---
id: {cn_id}
object_type: ConstraintMemory
title: "{cn_title}"
layer: DOMAIN
tier: hot
tags:
- meeting_order
- distilled
- fail-derived
confidence: 0.93
schema_version: 2
status: active
rule_id: {cn_id}
enforcement: reject
about_concepts:
- meeting_order
- booking
---

## HOW

{cn}

修复路径：{fix}

同源失败指纹：`{fp}`（轮次 {label}）

## WHEN

实现/修复 meeting_order 时强制遵守；违反即 FAIL。
"""
    (mem / f"{anti_id}.md").write_text(anti_body, encoding="utf-8")
    (mem / f"{cn_id}.md").write_text(cn_body, encoding="utf-8")
    print(f"  [distill] ANTI → {anti_id}")
    print(f"  [distill] CN   → {cn_id}  fingerprint={fp}")
    return {
        "fingerprint": fp,
        "anti_id": anti_id,
        "cn_id": cn_id,
        "fix": fix,
        "tip": tip,
    }


def seed_known_meeting_rules(ws: Path) -> None:
    """启动续跑前写入已知坑，避免 30B 重蹈覆辙。"""
    mem = ws / ".ontology_agent" / "memory" / "DOMAIN"
    mem.mkdir(parents=True, exist_ok=True)
    rules = [
        (
            "CN-MEETING-REPO-NAMES",
            "仓储只用 MeetingRepository + SqliteRepository + factory",
            "禁止 BaseRoomRepository / BaseBookingRepository / BaseRepository / "
            "SQLiteRoomRepository / repositories.booking / repositories.room / "
            "backend/src/repositories/（缺包名）。SqliteRepository() 无参。"
            "Protocol 方法：list_rooms/get_room/list_bookings/create_booking。",
        ),
        (
            "CN-MEETING-SEED-JSON",
            "种子 JSON 合法且走 ROOT 路径",
            "data/seed_rooms.json 必须是 JSON 数组；init_db 用 "
            "config.ROOT / 'data' / 'seed_rooms.json'；空表才插入。",
        ),
        (
            "CN-MEETING-SMALL-MODEL-UNIT",
            "小模型单文件 EP：命名/长度/引用自检",
            "1) 每轮只改 1 个具体文件（含扩展名），depends_on=[]；"
            "2) 函数/变量 snake_case，类 PascalCase，单文件 ≤220 行；"
            "3) 改前读目标文件+上游签名；每个 from X import Y 必须在依赖中存在；"
            "4) 禁止跨包、禁止 invent 新仓储模块；"
            "5) API→Service→Repository；domain 纯函数不碰 db。",
        ),
        (
            "CN-MEETING-NO-BASE-ROOM-REPO",
            "禁止拆分 Room/Booking 双仓储基类",
            "不得定义或 import BaseRoomRepository/BaseBookingRepository；"
            "单一 MeetingRepository Protocol + 单一 SqliteRepository 实现。"
            "factory 只返回 SqliteRepository。",
        ),
        (
            "CN-MEETING-IMPORT-RESOLVE",
            "import 必须可解析到现有文件",
            "写 from meeting_order.xxx import Y 前，确认 backend/src/meeting_order/xxx.py "
            "（或包 __init__）已存在；不要 import repositories.booking 这类虚构模块。",
        ),
        (
            "CN-MEETING-FE-WIRE",
            "前端三件套：rooms 下拉 / datetime-local / 提交后刷新",
            "BookingForm 必须接收 rooms 渲染 option；时间用 type=datetime-local；"
            "FormData+onSubmit；BookingPage 传 rooms={rooms}；成功后再 GET /bookings 并 setBookings。"
            "配套 tests：test_fe_wire_contract + test_fe_backend_flow（读→写→再读）。",
        ),
        (
            "CN-MEETING-API-URL-NORM",
            "API URL 规范化：前缀一次、资源路径分离",
            "1) config.API_V1_PREFIX='/api/v1' 只定义一次；"
            "2) router 只写 /rooms、/bookings，禁止含 /api/v1；"
            "3) main.include_router(..., prefix=API_V1_PREFIX)；"
            "4) 前端 apiBase 等于同一字符串，调用只写 /rooms、/bookings。"
            "双写会导致 /api/v1/api/v1/...→404。"
            "5) 测试里访问接口必须用全路径 /api/v1/rooms、/api/v1/bookings"
            "（TestClient 不经前端 apiBase，裸用 /rooms 会 404）。",
        ),
        (
            "CN-MEETING-FE-API-PATH",
            "前端调用遵守 API URL 规范（资源路径 only）",
            "服从 CN-MEETING-API-URL-NORM：apiGet('/rooms') 而非 apiGet('/api/v1/rooms')；"
            "client 须 joinApiPath。加载失败先查 URL 是否双写，再查后端是否宕机。",
        ),
        (
            "CN-MEETING-API-409",
            "API 必须把 rules 的 ValueError 转成 HTTP 409",
            "api/bookings.py 的 POST：整个检查+保存包在 try/except ValueError，"
            '转 HTTPException(409, detail={"code":"BOOKING_CONFLICT","message": str(e)})；'
            "禁止只包住 create_booking 而漏掉 check_no_overlap。",
        ),
        (
            "CN-MEETING-CONFIG-DBPATH",
            "SqliteRepository 必须运行时读 config.DB_PATH",
            "sqlite_repo.py 用 `import meeting_order.config as config` 与 "
            "self.db_path=config.DB_PATH；禁止 from config import DB_PATH（monkeypatch 失效）。",
        ),
        (
            "CN-MEETING-FACTORY-SEED",
            "factory.init_db 必须 seed_rooms_if_empty；get_repository 禁全局缓存",
            "factory.py 标准写法（照抄）：\n"
            "```python\n"
            "from meeting_order.repositories.sqlite_repo import SqliteRepository\n"
            "def init_db() -> None:\n"
            "    repo = SqliteRepository()\n"
            "    repo.seed_rooms_if_empty()\n"
            "def get_repository():\n"
            "    return SqliteRepository()\n"
            "```\n"
            "关键：1) init_db 调 repo.seed_rooms_if_empty()（缺则 GET /rooms 空）；"
            "2) get_repository() 每次返回新实例，禁止 global _repository 缓存——"
            "缓存会让 monkeypatch DB_PATH 失效（测试串库/404/409 误报）；"
            "3) sqlite_repo 的 seed_rooms_if_empty(self) 必须自包含，"
            "内部自己 sqlite3.connect(self.db_path)，禁止 def seed_rooms_if_empty(self, conn) 要外部传 conn。"
            "两边签名必须一致：无参 seed_rooms_if_empty()。"
        ),
        (
            "CN-MEETING-TEST-API-STATUS",
            "test_api：保留 scaffold fixture；成功预订 200/201；函数级临时库隔离",
            "scaffold 已预置 tests/meeting_order/test_api.py 的 fixture（def client(tmp_path, monkeypatch): "
            "monkeypatch config.DB_PATH 到 tmp，init_db，TestClient(app)）——必须保留这个 fixture，"
            "只补断言/测试用例，禁止改成 session 级或去掉 monkeypatch（否则用生产库串库/409 误报）。"
            "assert status_code in (200, 201)；冲突 detail.code==BOOKING_CONFLICT；"
            "用 client.get('/api/v1/bookings') 验列表。每个 test 用不同的时间或独立库。",
        ),
        (
            "PAT-MEETING-FE-API-FLOW",
            "FE↔API 集成流：rooms → POST → refresh bookings",
            "维护三步：GET /api/v1/rooms → POST /api/v1/bookings → GET /api/v1/bookings；"
            "再测重叠 409。小模型不必写完整 UI E2E，但必须有这条集成流 + FE 接线契约。",
        ),
    ]
    for mid, title, body in rules:
        path = mem / f"{mid}.md"
        # curated seeds are canonical: always overwrite so the latest contract wins
        # (learned memories from distill use different ids and are not overwritten here)
        if mid.startswith("PAT-"):
            object_type = "PatternMemory"
            enforcement = "prefer"
        elif mid.startswith("ANTI-"):
            object_type = "AntiPatternMemory"
            enforcement = "reject"
        else:
            object_type = "ConstraintMemory"
            enforcement = "reject"
        path.write_text(
            f"""---
id: {mid}
object_type: {object_type}
title: "{title}"
layer: DOMAIN
tier: hot
tags:
- meeting_order
- seeded
confidence: 0.95
schema_version: 2
status: active
rule_id: {mid}
enforcement: {enforcement}
about_concepts:
- meeting_order
- booking
---

## HOW

{body}

## WHEN

meeting_order 全流程强制。
""",
            encoding="utf-8",
        )
        print(f"  [seed-rule] {mid}")


def main() -> int:
    os.chdir(ROOT)
    os.environ["LLM_MODEL"] = FORCE_MODEL
    os.environ["DEMOCODE_ALLOW_STUB"] = "0"
    os.environ["DEMOCODE_GC_APPLY"] = "1"
    os.environ.pop("DEMOCODE_FORCE_STUB", None)
    os.environ["IFCLUB_APP"] = "meeting_order"

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir = ROOT / "logs" / f"meeting-30b-{ts}"
    log_dir.mkdir(parents=True, exist_ok=True)
    _tee(log_dir / "console.log")

    preserve = os.environ.get("PRESERVE_DISTILLED_MEMORY", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    print("=" * 60)
    print("meeting_order Session A/B ×10 — 全程 30B via EP")
    print(f"model={FORCE_MODEL}")
    print(f"log_dir={log_dir}")
    print(
        f"mode={'clean+keep distilled memory' if preserve else 'clean reset (no prior memory)'}"
    )
    print("=" * 60)

    from llm_chat import resolve_llm_model, chat_complete

    mid = resolve_llm_model()
    print(f"resolve_llm_model={mid}")
    if "30b" not in mid.lower() and "32b" not in mid.lower():
        print("ERROR: 未使用 30B/32B 级模型，中止")
        return 2
    ping = chat_complete("ping", "reply: ok", max_tokens=8)
    print(f"llm_ping={ping!r}")

    skip_reset = os.environ.get("SKIP_RESET", "").strip() in {"1", "true", "yes"}
    if skip_reset:
        print("SKIP_RESET=1 — keep existing workspace")
    else:
        print("\n== reset workspace ==")
        reset_workspace()

    from cli import _build_coordinator
    from core.task import Task
    from memory_ep_writeback import MemoryEPWriteback
    from harness.ep_promotion import EPPromotionGate
    from harness.verify_gate import VerifyResult, VerifyOutcome

    rounds = build_rounds()
    (log_dir / "rounds.json").write_text(
        json.dumps(rounds, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n== seed known meeting fail rules ==")
    seed_known_meeting_rules(WS)

    max_repair = int(os.environ.get("MAX_REPAIR_PER_ROUND", "3"))
    all_results: list[dict] = []
    seen_fps: dict[str, int] = {}

    start_from = os.environ.get("START_FROM_LABEL", "").strip()
    all_labels = [r["label"] for r in rounds]
    if start_from and start_from in all_labels:
        start_idx = all_labels.index(start_from)
        skip_labels = set(all_labels[:start_idx])
        print(f"START_FROM_LABEL={start_from} → 跳过 {len(skip_labels)} 轮")
    else:
        skip_labels = set()

    for sid in ("session-A", "session-B"):
        batch = [r for r in rounds if r["session"] == sid and r["label"] not in skip_labels]
        if not batch:
            continue
        print("\n" + "#" * 60)
        print(f"# SESSION {sid}  rounds={len(batch)}  (fail→distill→repair)")
        print("#" * 60)

        coord, _cfg = _build_coordinator(WS, apply=True, run_pytest=True)
        writeback = MemoryEPWriteback(coord._actions_by_domain)
        sess_items = []

        for r in batch:
            label = r["label"]
            gate = (r.get("gate_layer") or "domain").strip().lower()
            vite = bool(r.get("vite_build"))
            base_ctx = {
                "_session_id": sid,
                "_gate_layer": gate,
                "_max_units": int(r.get("max_units") or 2),
                "_pytest_paths": [
                    t.strip() for t in (r.get("tests") or "").split(",") if t.strip()
                ],
                "_skip_pytest": bool(r.get("skip_pytest"))
                or (vite and gate == "frontend"),
                "_vite_build": vite,
            }
            task_desc = r["task"]
            status = "failed"
            ep_id = None
            ep_status = None
            repairs = 0

            for attempt in range(0, max_repair + 1):
                anti = _recent_anti_hint(WS, limit=6)
                desc = task_desc
                if attempt == 0:
                    print(f"\n--- before {label} ---")
                else:
                    repairs = attempt
                    print(f"\n--- REPAIR {label} attempt={attempt}/{max_repair} ---")
                    # 根据最近失败指纹给硬点名文件，避免小模型死磕错误目标
                    force_file = ""
                    if (
                        "assert 0 ==" in anti
                        or "rooms == 4" in anti
                        or "len(rooms)" in anti
                        or "0 >= 2" in anti
                        or "至少一间启用" in anti
                    ):
                        force_file = (
                            "本轮必须只改 backend/src/meeting_order/repositories/factory.py："
                            "init_db() 创建 SqliteRepository() 后必须调用 "
                            "repo.seed_rooms_if_empty()（或等价种子）；禁止只建表不种子。"
                            "不要改 test_api.py。"
                        )
                    elif "assert 200 == 201" in anti or ("== 201" in anti and "test_api" in anti):
                        force_file = (
                            "本轮必须只改 tests/meeting_order/test_api.py："
                            "合法预订断言 status_code in (200, 201)；"
                            "不要用独立 repo fixture 第二套临时库；"
                            "用 client.get('/api/v1/bookings') 验证列表。"
                        )
                    elif "ValueError" in anti and "bookings.py" in anti:
                        force_file = (
                            "本轮必须只改 backend/src/meeting_order/api/bookings.py："
                            "捕获 ValueError→HTTP 409。"
                        )
                    elif "IMPORT-RESOLVE" in anti or "No module" in anti:
                        force_file = "本轮只改 import 出错的那一个源文件；先 rg 确认模块存在。"
                    desc = (
                        f"Repair `{label}`（attempt {attempt}）。"
                        f"{force_file}\n"
                        f"必须先避开以下已沉淀规则/ANTI，禁止重复同一错误：\n{anti}\n\n"
                        f"原任务：{task_desc}\n"
                        "强制 1 文件；先对齐上游签名与 import；禁止 Base*Repository。"
                    )
                    base_ctx = dict(base_ctx)
                    base_ctx["_max_units"] = 1  # Repair 强制单文件
                    base_ctx["_fix_mode"] = True

                ctx = dict(base_ctx)
                ctx["_recent_anti_hint"] = anti
                task = Task(description=desc, context=ctx)
                result = coord.run_ep(
                    task,
                    keywords=["meeting_order", "booking", "room", "fastapi", "schema"],
                )
                ep_id = result.ep_id
                ep_status = result.status
                print(result.summary())

                # EP 写回（含 FAIL→ANTI）；再用 distill 写会议域可执行规则
                try:
                    gate = EPPromotionGate()
                    vr = None
                    fb = task.context.get("_last_verify_feedback")
                    if isinstance(fb, dict):
                        vr = VerifyResult(
                            outcome=VerifyOutcome.FAIL_IMPL,
                            rule_id=str(fb.get("rule_id") or "TEST-FAIL"),
                            detail=str(fb.get("detail") or ""),
                            violations=list(fb.get("violations") or [])[:20],
                            command_output=str(fb.get("command_output") or "")[:2500],
                        )
                    promo = gate.plan_promotion(
                        result,
                        None,
                        verify_result=vr,
                        memory_ids=[],
                        bg_pending_count=0,
                    )
                    for pitem in promo.shared_items():
                        writeback.apply_item(
                            pitem,
                            task_description=desc,
                            primary_domain="code-arch",
                            dry_run=False,
                        )
                except Exception as exc:  # noqa: BLE001
                    print(f"  [writeback] skip: {exc}")

                if result.status == "completed":
                    status = "passed"
                    break

                fail_text = _collect_failure_text(WS, result)
                distilled = distill_failure_to_memory(
                    WS, label=label, fail_text=fail_text, attempt=attempt
                )
                fp = distilled["fingerprint"]
                seen_fps[fp] = seen_fps.get(fp, 0) + 1
                # 刷新联邦图，让下一轮读到新记忆
                try:
                    coord.fed_graph.load()
                    print("  [reload] FederatedGraph after distill")
                except Exception as exc:  # noqa: BLE001
                    print(f"  [reload] fail: {exc}")

                if seen_fps[fp] >= 2:
                    print(
                        f"  [loop-guard] fingerprint {fp} 已重复 {seen_fps[fp]} 次 → 加强约束"
                    )
                    # 写一条更硬的 CN，并强制下一轮 1 文件
                    hard = WS / ".ontology_agent" / "memory" / "DOMAIN"
                    hard.mkdir(parents=True, exist_ok=True)
                    hid = f"CN-MEETING-LOOP-{fp}"
                    (hard / f"{hid}.md").write_text(
                        f"""---
id: {hid}
object_type: ConstraintMemory
title: "循环失败 {fp}：禁止再写同一错误形态"
layer: DOMAIN
tier: hot
tags:
- meeting_order
- loop-guard
confidence: 0.98
schema_version: 2
status: active
rule_id: {hid}
enforcement: reject
---

## HOW

指纹 `{fp}` 已连续失败。下一轮必须：
1) 只改 1 个文件
2) 修复路径固定为：{distilled['fix']}
3) 改前用 rg 确认无虚构模块
4) 关键错误：{distilled['tip']}

## WHEN

Repair `{label}` 强制。
""",
                        encoding="utf-8",
                    )
                    print(f"  [loop-guard] wrote {hid}")
                    base_ctx["_max_units"] = 1

                if attempt >= max_repair:
                    break

            sess_items.append(
                {
                    "label": label,
                    "status": status,
                    "ep_id": ep_id,
                    "ep_status": ep_status,
                    "repairs": repairs,
                }
            )
            if status != "passed":
                print(f"STOP: {label} failed after {repairs} repairs")
                all_results.append({"session": sid, "items": sess_items})
                (log_dir / f"{sid}.json").write_text(
                    json.dumps(
                        {"session": sid, "items": sess_items},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                (log_dir / "FINAL_REPORT.json").write_text(
                    json.dumps(
                        {
                            "model": FORCE_MODEL,
                            "log_dir": str(log_dir),
                            "sessions": all_results,
                            "fingerprints": seen_fps,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                return 1

        all_results.append({"session": sid, "items": sess_items})
        (log_dir / f"{sid}.json").write_text(
            json.dumps({"session": sid, "items": sess_items}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # final verify
    print("\n== FINAL VERIFY ==")
    v = subprocess.run(
        [sys.executable, "cli.py", "verify", "--workspace", str(WS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    (log_dir / "FINAL.verify.log").write_text(
        (v.stdout or "") + (v.stderr or ""), encoding="utf-8"
    )
    print(v.stdout)
    print(v.stderr)

    final = {
        "model": mid,
        "log_dir": str(log_dir),
        "sessions": all_results,
        "verify_code": v.returncode,
        "fingerprints": seen_fps,
    }
    (log_dir / "FINAL_REPORT.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (log_dir / "DONE").write_text("ok\n" if v.returncode == 0 else "verify_failed\n")
    print(f"LOG_DIR={log_dir}")
    return 0 if v.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
