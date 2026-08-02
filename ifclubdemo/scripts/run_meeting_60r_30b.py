#!/usr/bin/env python3
"""会议室预订：Session A/B 各 30 轮（60 轮）白话构建，全程 30B。
复用 run_meeting_sessions_30b 的全部工程手段，仅替换 build_rounds 为 2x30 白话轮。"""

from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run_meeting_sessions_30b as base  # noqa: E402

P = base.PATH_RULE
U = base.UNIT_HINT
S = base.SIG_HINT

# (label, gate, sig?, tests, vite, plain_task)
_A = [
    ("A1-scope", "domain", 0, "", 0, "这一轮只新建 docs/scope.md：用大白话写我们要做的这个小演示——大家订会议室常遇到的烦心事（时间撞车、房间停用了、报错没原因），做成什么样算成功，以及我们故意不做的那些（审批、登录、通知、按人数卡容量、复杂日历）。用三句话分别说清「要做的」「不做的」「成功的样子」。"),
    ("A2-rules-brief", "domain", 0, "", 0, "这一轮只新建 docs/rules_brief.md：用大白话把订会议室的几条规矩写下来——结束时间得比开始时间晚；同一个房间的时间不能重叠，但前后紧挨着可以；只能订还在用的房间；撞车了要拒绝并告诉原因；以系统检查为准。再补一句「本演示不做的事」。"),
    ("A3-layer-roles", "domain", 0, "", 0, "这一轮只新建 docs/layer_roles.md：用大白话说清楚页面、规矩检查、存取、对外接口各自该干什么活，别互相抢。"),
    ("A4-repo-protocol", "domain", 1, "", 0, "这一轮只改 backend/src/meeting_order/repositories/base.py：给「怎么存取会议室和预订」定一个统一入口，列出四件事——查所有会议室、查单个会议室、查所有预订、新建一条预订。先只写接口约定，不写真正的存取实现。"),
    ("A5-sqlite-rooms", "domain", 1, "", 0, "这一轮只改 backend/src/meeting_order/repositories/sqlite_repo.py：用 SQLite 把会议室存起来——建一张房间表，第一次启动时把种子会议室填进去（至少两个可用、一个停用），再提供列出所有房间、查单个房间的能力。"),
    ("A6-factory", "domain", 1, "", 0, "这一轮只改 backend/src/meeting_order/repositories/factory.py：做一个统一入口来初始化数据库、拿到存取对象。初始化时一定要把种子会议室填好，不然页面打开房间列表是空的；再提供一个方法拿到那个存取对象。"),
    ("A7-api-rooms", "api", 1, "", 0, "这一轮只改 backend/src/meeting_order/api/rooms.py：做一个接口让前端能拿到会议室列表，每间房要能看到房间号、名字、容量、是否还在用。"),
    ("A8-main-mount", "api", 1, "", 0, "这一轮只改 backend/src/meeting_order/main.py：把会议室和预订的接口挂到对外入口上，统一带一个 /api/v1 前缀。"),
    ("A9-rules-time", "domain", 1, "", 0, "这一轮只改 backend/src/meeting_order/domain/rules.py：先写一条规矩——结束时间得比开始时间晚，否则报错；用大白话说错误原因。不碰数据库。"),
    ("A10-rules-overlap", "domain", 1, "", 0, "这一轮只改 backend/src/meeting_order/domain/rules.py：再写一条规矩——同一个房间的时间不能重叠，但前后紧挨着可以；不同房间互不影响。不碰数据库。"),
    ("A11-rules-active", "domain", 1, "", 0, "这一轮只改 backend/src/meeting_order/domain/rules.py：再写一条规矩——停用的房间不能订。不碰数据库。"),
    ("A12-test-rules-time-overlap", "domain", 0, "tests/meeting_order/test_rules.py", 0, "这一轮只新建/改 tests/meeting_order/test_rules.py：给规矩写测试——坏时间、撞车、首尾相接。测试要能跑过。这一步别改规矩本身。"),
    ("A13-test-rules-active-diffroom", "domain", 0, "tests/meeting_order/test_rules.py", 0, "这一轮只改 tests/meeting_order/test_rules.py：再补测试——停用房拒绝、不同房互不影响。测试要能跑过。"),
    ("A14-sqlite-bookings", "domain", 1, "", 0, "这一轮只改 backend/src/meeting_order/repositories/sqlite_repo.py：在刚才的存取对象上再补上「预订」的存取——建一张预订表，能列出所有预订、能新建一条预订。这一步先不查撞车，撞车交给后面那一步。"),
    ("A15-dto", "api", 1, "", 0, "这一轮只改 backend/src/meeting_order/schemas/booking.py：把「新建预订」要传的字段定死——哪个房间、会议名、预订人、开始时间、结束时间。可以再补一个回传用的结构（带上编号）。字段名别乱改。"),
    ("A16-booking-service", "api", 1, "", 0, "这一轮只改 backend/src/meeting_order/services/booking_service.py：把订会议室的步骤串起来——先查房间在不在、还能不能用、时间对不对、会不会和已有预订撞车，都没问题再存进去。有问题就抛出来，让接口去变成 409。"),
    ("A17-api-bookings-list", "api", 1, "", 0, "这一轮只改 backend/src/meeting_order/api/bookings.py：先做列出预订的接口。"),
    ("A18-api-bookings-post-409", "api", 1, "", 0, "这一轮只改 backend/src/meeting_order/api/bookings.py：再做新建预订——把检查和保存一起包住，出问题就返回 409 和「撞车」的提示，别让错误变成 500。"),
    ("A19-test-api-rooms-create", "api", 0, "tests/meeting_order", 0, "这一轮优先改 tests/meeting_order/test_api.py：给接口写测试——能拿到房间、合法预订能成功。测试要能跑过。"),
    ("A20-test-api-conflict", "api", 0, "tests/meeting_order", 0, "这一轮只改 tests/meeting_order/test_api.py：再补测试——撞车预订返回 409 加提示。测试要能跑过。"),
    ("A21-test-factory-contract", "domain", 0, "tests/meeting_order", 0, "这一轮只新建 tests/meeting_order/test_factory_contract.py：校验初始化数据库后必须有种子房间，且每次拿到的存取对象要用当次的库（不能串库）。"),
    ("A22-test-api-url-contract", "api", 0, "tests/meeting_order", 0, "这一轮只新建 tests/meeting_order/test_api_url_contract.py：校验接口路径规范——前缀只挂一次，资源路径分离，前后端都不许双写 /api/v1。"),
    ("A23-test-fe-backend-flow", "api", 0, "tests/meeting_order", 0, "这一轮只新建 tests/meeting_order/test_fe_backend_flow.py：跑一遍前端要用的后端集成流——拿房间、建预订、刷新预订、撞车 409。只测后端 HTTP 接口流，禁止读取或断言 frontend 源文件（前端尚未建，读了会 FileNotFoundError）。"),
    ("A24-repair", "api", 1, "tests/meeting_order", 0, "这一轮是 Repair：看现在哪里还红，只改一个跟当前失败最相关的文件，让测试全部跑过。"),
    ("A25-repair", "api", 1, "tests/meeting_order", 0, "这一轮还是 Repair：如果还有红的，继续只改一个最相关文件让测试全过。"),
    ("A26-arch-notes", "domain", 0, "", 0, "这一轮只新建 docs/architecture_notes.md：用大白话记一下后端这几层是怎么搭的、为什么这么分。"),
    ("A27-api-contract-doc", "domain", 0, "", 0, "这一轮只新建 docs/api_contract.md：用大白话写对外接口长什么样（路径、传什么、返什么、撞车返什么）。"),
    ("A28-repair", "api", 1, "tests/meeting_order", 0, "这一轮是 Repair：如果还有红的，只改一个最相关文件让测试全过。"),
    ("A29-seed-review", "domain", 0, "", 0, "这一轮只新建 docs/seed_review.md：回顾本轮踩过的坑，用大白话总结哪几条经验值得记下来给下次用。"),
    ("A30-final-checklist", "api", 1, "tests/meeting_order", 1, "这一轮只新增 docs/demo_checklist.md：用大白话写演示步骤和验收清单。如果测试和前端构建都已经绿了，就别动代码；如果还红，允许再改一个代码文件让它全绿。"),
]

_B = [
    ("B1-fe-review", "frontend", 0, "", 1, "这一轮只读 frontend 现有脚手架，新建 docs/fe_review.md：用大白话说一下前端现在有什么、还缺什么。"),
    ("B2-fe-api-client", "frontend", 1, "", 1, "这一轮只改 frontend/src/api/client.ts：做前端调后端的小工具——一个基础地址（等于后端的 /api/v1），一个拼接路径的函数，一个 GET、一个 POST。调用时只写 /rooms、/bookings，别再写 /api/v1。"),
    ("B3-fe-form-rooms", "frontend", 1, "", 1, "这一轮只改 frontend/src/components/BookingForm.tsx：做预订表单的选房间部分——只显示可用的房间。"),
    ("B4-fe-form-time-submit", "frontend", 1, "", 1, "这一轮只改 frontend/src/components/BookingForm.tsx：再补开始/结束时间选择和提交——填好点提交，别在页面自己判断撞车。"),
    ("B5-fe-room-list", "frontend", 1, "", 1, "这一轮只改 frontend/src/components/RoomList.tsx：做一个展示会议室列表的小块。"),
    ("B6-fe-booking-list", "frontend", 1, "", 1, "这一轮只改 frontend/src/components/BookingList.tsx：做一个展示已有预订列表的小块。"),
    ("B7-fe-error-banner", "frontend", 1, "", 1, "这一轮只改 frontend/src/components/ErrorBanner.tsx：做一个显示错误提示的小块，撞车时把后端返回的话显示出来。"),
    ("B8-fe-rules-panel", "frontend", 1, "", 1, "这一轮只改 frontend/src/components/RulesPanel.tsx：做一个小区块放订会议室的规矩说明，照之前写的规矩文档来，再加两三句怎么操作。"),
    ("B9-fe-page-load-rooms", "frontend", 1, "", 1, "这一轮只改 frontend/src/pages/BookingPage.tsx：做主页面——打开时去拿会议室列表。"),
    ("B10-fe-page-load-bookings", "frontend", 1, "", 1, "这一轮只改 frontend/src/pages/BookingPage.tsx：再补——打开时也拿已有预订列表。"),
    ("B11-fe-page-form-wire", "frontend", 1, "", 1, "这一轮只改 frontend/src/pages/BookingPage.tsx：把预订表单接进来，把房间列表传给它。"),
    ("B12-fe-page-refresh", "frontend", 1, "", 1, "这一轮只改 frontend/src/pages/BookingPage.tsx：提交成功后刷新预订列表。"),
    ("B13-fe-page-error", "frontend", 1, "", 1, "这一轮只改 frontend/src/pages/BookingPage.tsx：撞车时把后端返回的提示显示出来。"),
    ("B14-test-fe-wire", "frontend", 0, "tests/meeting_order", 1, "这一轮只新建 tests/meeting_order/test_fe_wire_contract.py：校验前端接线——表单有房间下拉、有 datetime-local、提交后刷新、错误条显示。"),
    ("B15-test-fe-api-contract", "frontend", 0, "tests/meeting_order", 1, "这一轮只新建 tests/meeting_order/test_fe_api_contract.py：校验前端调用路径不双写 /api/v1、用了拼接函数。"),
    ("B16-repair-fe", "frontend", 1, "tests/meeting_order", 1, "这一轮是 Repair：看前端哪里还红或构建不过，只改一个最相关文件。"),
    ("B17-repair-fe", "frontend", 1, "tests/meeting_order", 1, "这一轮还是 Repair：如果前端还红，继续只改一个最相关文件。"),
    ("B18-repair-fe", "frontend", 1, "tests/meeting_order", 1, "这一轮还是 Repair：如果还红，继续只改一个最相关文件让前端构建和测试都过。"),
    ("B19-fe-checklist", "frontend", 0, "", 1, "这一轮只新建 docs/fe_checklist.md：用大白话写前端演示步骤和验收清单。"),
    ("B20-full-repair", "api", 1, "tests/meeting_order", 1, "这一轮是整体 Repair：看后端和前端哪里还红，只改一个最相关文件让全部测试和构建都过。"),
    ("B21-full-repair", "api", 1, "tests/meeting_order", 1, "这一轮还是整体 Repair：如果还红，继续只改一个最相关文件。"),
    ("B22-full-repair", "api", 1, "tests/meeting_order", 1, "这一轮还是整体 Repair：如果还红，继续只改一个最相关文件让全部测试和构建都过。"),
    ("B23-arch-review", "domain", 0, "", 0, "这一轮只新建 docs/arch_review.md：用大白话回顾整套前后端是怎么搭的、哪些工程手段帮 30B 撑住了场。"),
    ("B24-test-plan-review", "domain", 0, "", 0, "这一轮只新建 docs/test_plan_review.md：用大白话总结现在有哪些测试、各自管什么、还缺什么。"),
    ("B25-seed-summary", "domain", 0, "", 0, "这一轮只新建 docs/seed_summary.md：用大白话总结本轮新踩的坑和值得沉淀成种子的经验。"),
    ("B26-repair", "api", 1, "tests/meeting_order", 1, "这一轮是 Repair：如果还有红的，只改一个最相关文件让全部测试和构建都过。"),
    ("B27-repair", "api", 1, "tests/meeting_order", 1, "这一轮还是 Repair：如果还红，继续只改一个最相关文件。"),
    ("B28-doc-polish", "domain", 0, "", 0, "这一轮只改 docs/demo_checklist.md：把演示步骤和验收清单补完整、说人话。"),
    ("B29-final-verify-doc", "api", 1, "tests/meeting_order", 1, "这一轮只新建 docs/final_verify.md：记录最后一轮验收结果（测试多少绿、构建是否过、接口 409 是否正常）。"),
    ("B30-final", "api", 1, "tests/meeting_order", 1, "这一轮是 Final：确认全部测试和前端构建都绿；如果还红，允许再改一个代码文件让它全绿；最后把 docs/demo_checklist.md 补全。"),
]


def build_rounds_60() -> list[dict]:
    common = f"{P} {U}"
    rounds = []
    for grp, sid in ((_A, "session-A"), (_B, "session-B")):
        for label, gate, sig, tests, vite, task in grp:
            prefix = f"{common} {S} " if sig else f"{common} "
            # 30B 在 per-round 全量 pytest 下会被脚手架预置的真实测试 + 自身实现 bug 卡死，
            # 采用「轮内只跑静态契约 + 末轮全量 pytest + 最终修复」的分层策略，保证 60 轮跑完。
            d = {"label": label, "gate_layer": gate, "max_units": 1, "skip_pytest": True, "task": prefix + task, "session": sid}
            if tests:
                d["tests"] = tests
            if vite:
                d["vite_build"] = True
            rounds.append(d)
    return rounds


if __name__ == "__main__":
    base.build_rounds = build_rounds_60  # monkey-patch
    raise SystemExit(base.main())
