#!/usr/bin/env python3
"""
2 会话 × 10 轮（共 20 轮）EP 重建 oncall 前后端排班系统。

强制小模型：qwen3-coder-30b-a3b-instruct（可用 DEMOCODE_FORCE_MODEL 覆盖，
须含 30b/32b；禁止 stub / 大模型）。
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
        shutil.rmtree(ws)

    subprocess.run([sys.executable, "cli.py", "init-app", "oncall"], cwd=ROOT, check=True)

    for cmd, f in (
        ("inject", "docs/business_brief.md"),
        ("inject-arch", "docs/architecture_brief.md"),
    ):
        subprocess.run(
            [sys.executable, "cli.py", cmd, f, "--workspace", str(ws)],
            cwd=ROOT,
            check=False,
        )


def build_rounds() -> list[dict]:
    """20 轮微步骤：Impl / Test / Repair 分离；签名注入由 harness 自动完成。"""
    s1 = [
        {
            "label": "S1-R01-models-engineer",
            "gate_layer": "domain",
            "max_units": 1,
            "tests": "tests/oncall/test_rules.py",
            "task": "只改 1 文件 models/engineer.py：Engineer(id Optional[int], name, is_active)。对齐 oncall_schema.json。",
        },
        {
            "label": "S1-R02-models-shift-roster",
            "gate_layer": "domain",
            "max_units": 2,
            "tests": "tests/oncall/test_rules.py",
            "freeze_after": ["backend/src/oncall/models/"],
            "task": "最多 2 文件：shift.py + roster.py（或含 __init__ re-export）。Roster 仅 shifts，禁止 engineers。完成后 freeze models。",
        },
        {
            "label": "S1-R03-db",
            "gate_layer": "domain",
            "max_units": 1,
            "tests": "tests/oncall/test_rules.py",
            "task": "只改 db.py：init_db/create_engineer/list_engineers。禁止改 models/。对齐 Engineer 签名。",
        },
        {
            "label": "S1-R04-rules",
            "gate_layer": "domain",
            "max_units": 1,
            "tests": "tests/oncall/test_rules.py",
            "task": "只改 domain/rules.py：RuleViolation + validate_roster(roster, engineers) 纯函数。禁止改 models/。",
        },
        {
            "label": "S1-R05-test-rules",
            "gate_layer": "domain",
            "max_units": 2,
            "tests": "tests/oncall/test_rules.py",
            "task": "最多 2 文件：conftest.py + test_rules.py。禁止改 models/。pytest 须绿。",
        },
        {
            "label": "S1-R06-fix-rules",
            "gate_layer": "domain",
            "max_units": 2,
            "tests": "tests/oncall/test_rules.py",
            "task": "Repair：只修 rules 或 tests（≤2 文件）至 test_rules 全绿。参考 ANTI。禁止 models/。",
        },
        {
            "label": "S1-R07-main-health",
            "gate_layer": "domain",
            "max_units": 1,
            "tests": "tests/oncall/test_rules.py",
            "task": "只改 main.py：FastAPI+/health+lifespan init_db。禁止 models/。",
        },
        {
            "label": "S1-R08-scheduler-impl",
            "gate_layer": "domain",
            "max_units": 1,
            "tests": "tests/oncall/test_rules.py",
            "task": "只改 domain/scheduler.py：generate_week→Roster(shifts=...)。先读上游签名。禁止 models/ 与测试文件。",
        },
        {
            "label": "S1-R09-scheduler-test",
            "gate_layer": "domain",
            "max_units": 1,
            "tests": "tests/oncall/test_scheduler.py",
            "task": "只改 test_scheduler.py（≥3 active 成功；无 active 抛 RuleViolation）。禁止改生产代码与 models/。",
        },
        {
            "label": "S1-R10-scheduler-repair",
            "gate_layer": "domain",
            "max_units": 2,
            "tests": "tests/oncall/test_rules.py,tests/oncall/test_scheduler.py",
            "task": "Repair：只修 scheduler.py 和/或 test_scheduler.py（≤2）至全绿。参考 ANTI。禁止 models/。",
        },
    ]
    s2 = [
        {
            "label": "S2-R11-api-engineers",
            "gate_layer": "api",
            "max_units": 1,
            "tests": "tests/oncall/test_rules.py",
            "task": "只改 api/engineers.py：CreateEngineerRequest；GET/POST；正确 response_model。用 db，禁止 Roster.engineers。禁止 models/。",
        },
        {
            "label": "S2-R12-api-engineers-wire",
            "gate_layer": "api",
            "max_units": 1,
            "tests": "tests/oncall/test_rules.py",
            "task": "只改 main.py：挂载 engineers 路由（若已挂载则小修 import）。禁止 models/ 与 frontend。",
        },
        {
            "label": "S2-R13-api-roster",
            "gate_layer": "api",
            "max_units": 1,
            "tests": "tests/oncall/test_scheduler.py",
            "task": "只改 api/roster.py：POST /generate；409 detail.code=ROSTER_CONFLICT；调用 scheduler。禁止 models/。",
        },
        {
            "label": "S2-R14-test-api-roster",
            "gate_layer": "api",
            "max_units": 1,
            "tests": "tests/oncall/test_api_roster.py",
            "task": "只写/改 test_api_roster.py。禁止改生产代码与 models/。",
        },
        {
            "label": "S2-R15-fix-api",
            "gate_layer": "api",
            "max_units": 2,
            "tests": "tests/oncall/test_api_roster.py,tests/oncall/test_api_smoke.py,tests/oncall/test_rules.py",
            "task": "Repair API：≤2 文件（api/* 或 tests/* 或 main）。可补 test_api_smoke。参考 ANTI。禁止 models/frontend。",
        },
        {
            "label": "S2-R16-fe-client",
            "gate_layer": "frontend",
            "max_units": 1,
            "tests": "",
            "vite_build": True,
            "task": "只改 frontend/src/api/client.ts。禁止 @/。门禁=vite build。",
        },
        {
            "label": "S2-R17-fe-engineers-page",
            "gate_layer": "frontend",
            "max_units": 2,
            "tests": "",
            "vite_build": True,
            "task": "最多 2 前端文件实现 EngineersPage（相对 import，字段 name/is_active）。门禁=vite build。",
        },
        {
            "label": "S2-R18-fe-roster-page",
            "gate_layer": "frontend",
            "max_units": 2,
            "tests": "",
            "vite_build": True,
            "task": "最多 2 文件：RosterWeekPage(+WeekGrid)。展示 engineer_id/date/shift_type。门禁=vite build。",
        },
        {
            "label": "S2-R19-fe-shell",
            "gate_layer": "frontend",
            "max_units": 2,
            "tests": "",
            "vite_build": True,
            "task": "App 路由 + favicon/index.html（≤2 相关改动）。禁止 @/。门禁=vite build。",
        },
        {
            "label": "S2-R20-final-api",
            "gate_layer": "api",
            "max_units": 2,
            "tests": "tests/oncall/test_api_smoke.py,tests/oncall/test_rules.py,tests/oncall/test_scheduler.py",
            "task": "Final Repair：≤2 后端文件使 scoped 测试绿。禁止 models/ 与 frontend。",
        },
    ]
    rounds = []
    for r in s1:
        r["session"] = "session-A"
        rounds.append(r)
    for r in s2:
        r["session"] = "session-B"
        rounds.append(r)
    assert len(rounds) == 20
    return rounds


def _recent_anti_hint(ws: Path, limit: int = 3) -> str:
    root = ws / ".ontology_agent" / "memory"
    if not root.exists():
        return ""
    files = sorted(root.rglob("ANTI-EP-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
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
        chunks.append(f"### {p.stem}\n{title}\n" + "\n".join(how[:8]))
    return "\n\n".join(chunks)


def audit_prompt(fed, domain_configs, task_desc: str, log_dir: Path, label: str) -> dict:
    from agent_memory_scope import AgentMemoryScope
    from memory_prompt_builder import MemoryPromptBuilder

    scope = AgentMemoryScope(
        agent_name="AuditPrompt",
        domains=["code-arch", "domain"],
        tiers=["hot", "warm", "cold"],
        read_layers=["critical", "rule", "context", "pattern"],
        write_layers=[],
        budget_multiplier=1.0,
        concept_hints=["oncall", "roster", "architecture"],
    )
    builder = MemoryPromptBuilder(fed, domain_configs, global_token_cap=900)
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
    os.environ["LLM_MODEL"] = FORCE_MODEL
    os.environ["DEMOCODE_ALLOW_STUB"] = "0"
    os.environ["DEMOCODE_GC_APPLY"] = "1"
    os.environ["DEMOCODE_GC_AGE_STEP"] = "0.12"
    os.environ["DEMOCODE_COLD_BUDGET"] = "200"
    os.environ.pop("DEMOCODE_FORCE_STUB", None)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir = ROOT / "logs" / f"twosession-{ts}"
    log_dir.mkdir(parents=True, exist_ok=True)
    _tee(log_dir / "console.log")

    print("=" * 60)
    print("twosession rebuild oncall (2×10=20)")
    print(f"model={FORCE_MODEL}")
    print(f"log_dir={log_dir}")
    print("=" * 60)

    from llm_chat import resolve_llm_model, chat_complete

    mid = resolve_llm_model()
    print(f"resolve_llm_model={mid}")
    if "30b" not in mid.lower() and "32b" not in mid.lower():
        print("ERROR: 未使用 30B/32B 级模型，中止")
        return 2
    ping = chat_complete("ping", "reply: ok", max_tokens=8)
    print(f"llm_ping={ping!r}")

    # 清理旧 oncall 相关 workspace
    for name in ("oncall", "oncall_test"):
        p = ROOT / "workspace" / name
        if p.exists():
            print(f"removing {p}")
            shutil.rmtree(p)

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

    sessions = ["session-A", "session-B"]
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
            gate = (r.get("gate_layer") or "domain").strip().lower()
            vite = bool(r.get("vite_build")) or gate == "frontend"
            ctx = {
                "_session_id": sid,
                "_gate_layer": gate,
                "_max_units": int(r.get("max_units") or (1 if gate != "frontend" else 2)),
                "_pytest_paths": [
                    t.strip()
                    for t in (r.get("tests") or "").split(",")
                    if t.strip()
                ],
                "_skip_pytest": vite and gate == "frontend",
                "_vite_build": vite,
            }
            if r.get("freeze_after"):
                ctx["_freeze_after"] = list(r["freeze_after"])
            items.append(
                EpQueueItem(
                    ep_label=r["label"],
                    task=Task(description=r["task"], context=ctx),
                    keywords=["oncall", "roster", "fastapi", "schema"],
                    depends_on=None,
                )
            )

        def pre_hook(item: EpQueueItem):
            # 置顶最近 ANTI，供 Repair / CA 使用
            item.task.context = item.task.context or {}
            item.task.context["_recent_anti_hint"] = _recent_anti_hint(ws, limit=3)
            print(f"\n--- prompt audit before {item.ep_label} ---")
            audit_prompt(fed, domain_configs, item.task.description, log_dir, item.ep_label)

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
    print(
        json.dumps(
            {
                "model": mid,
                "shared_md": len(final["shared_memory_files"]),
                "session_files": len(final["session_archives"]),
                "tiers": final["tier_snapshot"]["shared"],
                "sessions": final["tier_snapshot"]["sessions"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"LOG_DIR={log_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
