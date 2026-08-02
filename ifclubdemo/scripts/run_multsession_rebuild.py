#!/usr/bin/env python3
"""
多会话 × 30 轮 EP 重建 oncall，触发：
  - 共享记忆写回（PromotionGate → DEC / BIZ-PAT）
  - 会话记忆归档（sessions/<id>/archive.jsonl）
  - EP 空闲 GC / age / 冷热切换
  - MemoryPromptBuilder 四段审计日志

强制模型：qwen3-coder-30b-a3b-instruct（可用 DEMOCODE_FORCE_MODEL 覆盖）
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


def reset_workspace(ws: Path) -> None:
    if ws.exists():
        # 保留 docs brief 副本到 tmp
        briefs = {}
        for name in ("business_brief.md", "architecture_brief.md"):
            p = ws / "docs" / name
            if p.exists():
                briefs[name] = p.read_text(encoding="utf-8")
        shutil.rmtree(ws)
    else:
        briefs = {}

    subprocess.run([sys.executable, "cli.py", "init-app", "oncall"], cwd=ROOT, check=True)
    # 若 scaffold 已带 brief，inject；否则写回
    for name, text in briefs.items():
        dest = ws / "docs" / name
        if not dest.exists() and text:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")

    for cmd, f in (
        ("inject", "docs/business_brief.md"),
        ("inject-arch", "docs/architecture_brief.md"),
    ):
        path = ws / f if not Path(f).is_absolute() else Path(f)
        # cli 相对 workspace
        subprocess.run(
            [sys.executable, "cli.py", cmd, f, "--workspace", str(ws)],
            cwd=ROOT,
            check=False,
        )


def build_rounds() -> list[dict]:
    """30 轮：3 会话 × 10 轮微任务（拉长构建过程）。"""
    s1 = [
        {
            "label": "S1-R01-models-engineer",
            "tests": "tests/oncall/test_rules.py",
            "task": "仅实现 backend/src/oncall/models/engineer.py：dataclass Engineer(id Optional[int], name, is_active)。Python3.9。不要写 API。",
        },
        {
            "label": "S1-R02-models-shift",
            "tests": "tests/oncall/test_rules.py",
            "task": "实现 backend/src/oncall/models/shift.py：Shift(id, engineer_id, date:str, shift_type)。禁止 shift_date。对齐已有 engineer。",
        },
        {
            "label": "S1-R03-models-roster",
            "tests": "tests/oncall/test_rules.py",
            "task": "实现 backend/src/oncall/models/roster.py 与 models/__init__.py re-export。Roster(shifts)。",
        },
        {
            "label": "S1-R04-db",
            "tests": "tests/oncall/test_rules.py",
            "task": "实现 backend/src/oncall/db.py：sqlite3 init_db/create_engineer(id=None 可自增)/list_engineers。DB_PATH 可配置。",
        },
        {
            "label": "S1-R05-rules",
            "tests": "tests/oncall/test_rules.py",
            "task": "实现 domain/rules.py：RuleViolation + validate_roster(roster, engineers) 纯函数（禁止调 db）。双班/非active/连续>3/每日 primary。",
        },
        {
            "label": "S1-R06-test-rules",
            "tests": "tests/oncall/test_rules.py",
            "task": "写 tests/oncall/conftest.py（monkeypatch DB_PATH）与 test_rules.py，覆盖上述规则。使 pytest 通过。",
        },
        {
            "label": "S1-R07-fix-rules",
            "tests": "tests/oncall/test_rules.py",
            "task": "若 test_rules 未全绿则修复；已绿则小幅补充一条合法排班用例。不要改 API。",
        },
        {
            "label": "S1-R08-main-health",
            "tests": "tests/oncall/test_rules.py",
            "task": "确保 backend/src/oncall/main.py 有 FastAPI app、/health、lifespan 调 init_db。不要破坏已有 models/rules。",
        },
        {
            "label": "S1-R09-memory-touch",
            "tests": "tests/oncall/test_rules.py",
            "task": "只改 tests：增加一条文档字符串说明规则来自 CN-ONCALL 记忆；保持全部测试通过。",
        },
        {
            "label": "S1-R10-verify",
            "tests": "tests/oncall/test_rules.py",
            "task": "回归修复：确保 tests/oncall/test_rules.py 全绿；必要时微调 rules/db。",
        },
    ]
    s2 = [
        {
            "label": "S2-R11-scheduler",
            "tests": "tests/oncall/test_scheduler.py,tests/oncall/test_rules.py",
            "task": "实现 domain/scheduler.py：generate_week(week_start, engineers)->Roster；仅 active；空列表抛 RuleViolation；须通过已有 validate_roster。复用 Shift 字段。",
        },
        {
            "label": "S2-R12-test-scheduler",
            "tests": "tests/oncall/test_scheduler.py",
            "task": "写/修 test_scheduler.py（≥3 active 成功；无 active 抛 RuleViolation）。不要发明 RosterEntry。",
        },
        {
            "label": "S2-R13-api-roster",
            "tests": "tests/oncall/test_scheduler.py,tests/oncall/test_api_roster.py",
            "task": "实现 api/roster.py POST /generate；409 detail.code=ROSTER_CONFLICT；挂到 main。",
        },
        {
            "label": "S2-R14-test-api-roster",
            "tests": "tests/oncall/test_api_roster.py",
            "task": "写 test_api_roster：tmp DB；≥3 active→200；冲突→409 detail.code。",
        },
        {
            "label": "S2-R15-api-engineers",
            "tests": "tests/oncall/test_api_roster.py,tests/oncall/test_rules.py",
            "task": "实现 api/engineers.py：Pydantic CreateEngineerRequest(name,is_active)；GET/POST；禁止把 Engineer 直接当请求体。",
        },
        {
            "label": "S2-R16-smoke",
            "tests": "tests/oncall/test_api_smoke.py",
            "task": "写 test_api_smoke：health；创建≥3 工程师；generate roster 200。",
        },
        {
            "label": "S2-R17-fix-api",
            "tests": "tests/oncall/test_api_smoke.py,tests/oncall/test_api_roster.py",
            "task": "修复 API/测试使 scoped pytest 通过；复用共享记忆中的路径约定。",
        },
        {
            "label": "S2-R18-conftest",
            "tests": "tests/oncall",
            "task": "统一 conftest monkeypatch oncall.db.DB_PATH；全量 tests/oncall 尽量绿。",
        },
        {
            "label": "S2-R19-shared-reuse",
            "tests": "tests/oncall/test_rules.py",
            "task": "根据已有共享 DEC/Pattern 记忆，只做小修复让 test_rules 保持绿（演示跨会话复用共享记忆）。",
        },
        {
            "label": "S2-R20-verify",
            "tests": "tests/oncall",
            "task": "后端回归：tests/oncall 尽可能全绿。",
        },
    ]
    s3 = [
        {
            "label": "S3-R21-fe-client",
            "tests": "tests/oncall",
            "task": "只改 frontend/src/api/client.ts：apiGet/apiPost，基址 /api/v1；禁止首行 typescript 标签；禁止 @/。",
        },
        {
            "label": "S3-R22-fe-engineers",
            "tests": "tests/oncall",
            "task": "实现 EngineersPage：相对路径 import；创建 {name,is_active}；列表 id/name/is_active。",
        },
        {
            "label": "S3-R23-fe-roster",
            "tests": "tests/oncall",
            "task": "实现 RosterWeekPage + WeekGrid：POST /roster/generate {week_start}；展示 engineer_id/date/shift_type。",
        },
        {
            "label": "S3-R24-fe-rules-app",
            "tests": "tests/oncall",
            "task": "RulesPage + App.tsx 路由；相对 import；后端测试仍绿。",
        },
        {
            "label": "S3-R25-fe-favicon",
            "tests": "tests/oncall",
            "task": "frontend/public/favicon.svg+ico 与 index.html link，消除 favicon 404。",
        },
        {
            "label": "S3-R26-fe-fix-alias",
            "tests": "tests/oncall",
            "task": "扫描 frontend/src 去掉任何 @/；修正错误字段。",
        },
        {
            "label": "S3-R27-integrate",
            "tests": "tests/oncall",
            "task": "联调修复：backend+tests 全绿；前端相对 import。",
        },
        {
            "label": "S3-R28-session-only",
            "tests": "tests/oncall/test_rules.py",
            "task": "故意小改 test_rules 文档注释（会话痕迹）；保持绿。用于对比会话归档 vs 共享 DEC。",
        },
        {
            "label": "S3-R29-gc-pressure",
            "tests": "tests/oncall/test_rules.py",
            "task": "再写一条简短决策性注释到 test_rules（制造更多 EP 写回压力，便于 GC 衰减）。测试须绿。",
        },
        {
            "label": "S3-R30-final",
            "tests": "tests/oncall",
            "task": "最终验收：tests/oncall 全绿；必要时最小修复。",
        },
    ]
    rounds = []
    for r in s1:
        r["session"] = "session-A"
        rounds.append(r)
    for r in s2:
        r["session"] = "session-B"
        rounds.append(r)
    for r in s3:
        r["session"] = "session-C"
        rounds.append(r)
    assert len(rounds) == 30
    return rounds


def audit_prompt(fed, domain_configs, task_desc: str, log_dir: Path, label: str) -> dict:
    from agent_memory_scope import AgentMemoryScope
    from memory_prompt_builder import MemoryPromptBuilder

    # 审计用：读 hot/warm/cold，观察冷热切换
    scope = AgentMemoryScope(
        agent_name="AuditPrompt",
        domains=["code-arch", "domain"],
        tiers=["hot", "warm", "cold"],
        read_layers=["critical", "rule", "context", "pattern"],
        write_layers=[],
        budget_multiplier=1.0,
        concept_hints=["oncall", "roster", "architecture"],
    )
    builder = MemoryPromptBuilder(
        fed, domain_configs, global_token_cap=900
    )
    result = builder.build(scope, task_desc, keywords=["oncall", "roster"])
    payload = {
        "label": label,
        "summary": result.summary(),
        "memory_ids": result.memory_ids,
        "dropped_ids": result.dropped_ids,
        "route_intent": result.route_intent,
        "route_domains": result.route_domains,
        "ep_writeback_ids": result.ep_writeback_ids(),
        "stages": [
            {
                "name": s.name,
                "hits": s.hit_count,
                "tokens": s.tokens,
                "notes": s.notes,
            }
            for s in result.stages
        ],
    }
    out = log_dir / "prompt_audits.jsonl"
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    print(result.summary())
    return payload


def tier_snapshot(ws: Path) -> dict:
    snap = {"shared": {}, "sessions": {}}
    for kind, root in (
        ("domain", ws / ".ontology_agent" / "memory"),
        ("code-arch", ws / ".ontology_agent" / "arch_memory"),
    ):
        tiers: dict[str, list] = {}
        if root.exists():
            for p in root.rglob("*.md"):
                text = p.read_text(encoding="utf-8", errors="replace")
                tier = "unknown"
                conf = None
                nid = p.stem
                for line in text.splitlines()[:40]:
                    if line.startswith("tier:"):
                        tier = line.split(":", 1)[1].strip()
                    if line.startswith("confidence:"):
                        try:
                            conf = float(line.split(":", 1)[1].strip())
                        except ValueError:
                            pass
                    if line.startswith("gc_note:"):
                        pass
                tiers.setdefault(tier, []).append({"id": nid, "confidence": conf})
        snap["shared"][kind] = {t: len(v) for t, v in tiers.items()}
        snap["shared"][f"{kind}_nodes"] = tiers
    sess_root = ws / ".ontology_agent" / "sessions"
    if sess_root.exists():
        for d in sess_root.iterdir():
            if d.is_dir():
                arch = d / "archive.jsonl"
                snap["sessions"][d.name] = {
                    "archive_lines": (
                        sum(1 for _ in arch.open(encoding="utf-8")) if arch.exists() else 0
                    )
                }
    return snap


def main() -> int:
    os.chdir(ROOT)
    # 强制 32B Coder 模型
    os.environ["LLM_MODEL"] = FORCE_MODEL
    os.environ["DEMOCODE_ALLOW_STUB"] = "0"
    os.environ["DEMOCODE_GC_APPLY"] = "1"
    os.environ["DEMOCODE_GC_AGE_STEP"] = "0.12"
    os.environ["DEMOCODE_COLD_BUDGET"] = "200"
    os.environ.pop("DEMOCODE_FORCE_STUB", None)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir = ROOT / "logs" / f"multsession-{ts}"
    log_dir.mkdir(parents=True, exist_ok=True)
    _tee(log_dir / "console.log")

    print("=" * 60)
    print("multsession rebuild oncall")
    print(f"model={FORCE_MODEL}")
    print(f"log_dir={log_dir}")
    print("=" * 60)

    # 校验模型 id
    from llm_chat import resolve_llm_model, chat_complete

    mid = resolve_llm_model()
    print(f"resolve_llm_model={mid}")
    if "30b" not in mid and "32b" not in mid:
        print("ERROR: 未使用 30B/32B 级模型，中止")
        return 2
    ping = chat_complete("ping", "reply: ok", max_tokens=8)
    print(f"llm_ping={ping!r}")

    ws = ROOT / "workspace" / "oncall"
    print("\n== reset workspace ==")
    reset_workspace(ws)

    from cli import _build_coordinator
    from core.task import Task
    from ep_queue import EpQueue, EpQueueItem
    from memory_ep_writeback import MemoryEPWriteback

    rounds = build_rounds()
    (log_dir / "rounds.json").write_text(
        json.dumps(rounds, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 按会话分批跑（共享记忆保留在 workspace；会话目录分离）
    sessions = ["session-A", "session-B", "session-C"]
    all_results = []

    for sid in sessions:
        batch = [r for r in rounds if r["session"] == sid]
        print("\n" + "#" * 60)
        print(f"# SESSION {sid}  rounds={len(batch)}")
        print("#" * 60)

        coord, cfg = _build_coordinator(ws, apply=True, run_pytest=True)
        fed = coord.fed_graph
        domain_configs = coord.domain_configs
        actions = coord._actions_by_domain
        ops = coord.memory_ops

        def reload_fn():
            fed.load()
            print("  [reload] FederatedGraph reloaded")

        queue = EpQueue(
            coord,
            MemoryEPWriteback(actions),
            reload_fn=reload_fn,
            primary_domain="code-arch",
            memory_ops=ops,
            session_id=sid,
        )

        items = []
        for r in batch:
            items.append(
                EpQueueItem(
                    ep_label=r["label"],
                    task=Task(
                        description=r["task"],
                        context={
                            "_session_id": sid,
                            "_pytest_paths": [
                                t.strip()
                                for t in (r.get("tests") or "").split(",")
                                if t.strip()
                            ],
                        },
                    ),
                    keywords=["oncall", "roster", "fastapi"],
                    depends_on=None,  # 不熔断整链；每轮独立
                )
            )

        def pre_hook(item: EpQueueItem):
            print(f"\n--- prompt audit before {item.ep_label} ---")
            audit_prompt(fed, domain_configs, item.task.description, log_dir, item.ep_label)
            # 同步 tests 到 verify（coordinator 从 task.context 读）
            # VerifyGate 使用 _pytest_paths
            pass

        # 需要把 _pytest_paths 接到 VerifyGate：检查 ep_coordinator / verify
        # 已有 task.context.get("_pytest_paths")
        qres = queue.run(items, dry_run=False, pre_run_hook=pre_hook, fuse_on_fail=False)
        print(qres.summary())

        sess_report = {
            "session": sid,
            "summary": qres.summary(),
            "ops_reports": qres.ops_reports,
            "final_ops": qres.final_ops.to_dict() if qres.final_ops else None,
            "items": [
                {
                    "label": it.ep_label,
                    "status": it.status.value,
                    "shared_written": it.written_ids,
                    "ep_id": it.ep_result.ep_id if it.ep_result else None,
                    "ep_status": it.ep_result.status if it.ep_result else None,
                }
                for it in qres.items
            ],
            "tier_snapshot": tier_snapshot(ws),
        }
        (log_dir / f"{sid}.json").write_text(
            json.dumps(sess_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        all_results.append(sess_report)

    # 终局对比：共享 vs 会话
    final = {
        "model": mid,
        "log_dir": str(log_dir),
        "sessions": all_results,
        "tier_snapshot": tier_snapshot(ws),
        "shared_memory_files": sorted(
            str(p.relative_to(ws))
            for p in (ws / ".ontology_agent").rglob("*.md")
            if "sessions" not in p.parts
        ),
        "session_archives": sorted(
            str(p.relative_to(ws))
            for p in (ws / ".ontology_agent" / "sessions").rglob("*")
            if p.is_file()
        )
        if (ws / ".ontology_agent" / "sessions").exists()
        else [],
    }
    (log_dir / "FINAL_REPORT.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (log_dir / "DONE").write_text("ok\n", encoding="utf-8")
    print("\n== FINAL ==")
    print(json.dumps({
        "model": mid,
        "shared_md": len(final["shared_memory_files"]),
        "session_files": len(final["session_archives"]),
        "tiers": final["tier_snapshot"]["shared"],
        "sessions": final["tier_snapshot"]["sessions"],
    }, ensure_ascii=False, indent=2))
    print(f"LOG_DIR={log_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
