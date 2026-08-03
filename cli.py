#!/usr/bin/env python3
"""
democode 统一 CLI

  python cli.py doctor
  python cli.py init --workspace ./workspace/app
  python cli.py init-app meeting_order --workspace ./workspace/meeting_order
  python cli.py inject docs/business_brief.md --workspace ./workspace/meeting_order
  python cli.py run --workspace ./workspace/app --task "..." --no-llm
  python cli.py fix --workspace ./workspace/meeting_order --task "修复冲突检测" --files backend/src/meeting_order/domain/rules.py
  python cli.py verify --workspace ./workspace/meeting_order
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

DEMOCODE_ROOT = Path(__file__).resolve().parent
PHASE6 = DEMOCODE_ROOT / "phase6"
PHASE7 = DEMOCODE_ROOT / "phase7"
PHASE8 = DEMOCODE_ROOT / "phase8"

sys.path.insert(0, str(DEMOCODE_ROOT))
sys.path.insert(0, str(PHASE6))
sys.path.insert(0, str(PHASE7))
sys.path.insert(0, str(PHASE8))

from cli_support.inject_brief import inject_business_brief  # noqa: E402
from llm_chat import is_llm_available, llm_mode_label, set_force_stub  # noqa: E402
from workspace_config import WorkspaceConfig  # noqa: E402


def _default_workspace() -> Path:
    return DEMOCODE_ROOT / "workspace" / "app"


def cmd_doctor(args: argparse.Namespace) -> int:
    ws = Path(args.workspace).resolve()
    print("== doctor ==")
    print(f"  democode : {DEMOCODE_ROOT}")
    print(f"  workspace: {ws} exists={ws.exists()}")
    print(f"  LLM      : {llm_mode_label()}")
    print(f"  API key  : {'yes' if is_llm_available() else 'no'}")
    cfg_path = ws / "workspace.toml"
    print(f"  workspace.toml: {'yes' if cfg_path.exists() else 'no'}")
    if cfg_path.exists():
        cfg = WorkspaceConfig.load(ws)
        print(f"  app_entry: {cfg.app_entry or '-'}")
        print(f"  test_cmd : {cfg.test_cmd}")
    # deps
    for mod in ("openai", "fastapi", "pytest"):
        try:
            __import__(mod)
            print(f"  py:{mod}: ok")
        except ImportError:
            print(f"  py:{mod}: missing")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    ws = Path(args.workspace).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    cfg = WorkspaceConfig(name=ws.name, root=ws)
    cfg.save()
    (ws / "src").mkdir(exist_ok=True)
    (ws / "tests").mkdir(exist_ok=True)
    (ws / ".ontology_agent" / "memory").mkdir(parents=True, exist_ok=True)
    (ws / ".ontology_agent" / "backup").mkdir(parents=True, exist_ok=True)
    # 链接/提示 code-arch 记忆位置（不强制复制，避免污染）
    readme = ws / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# {ws.name}\n\n由 democode CLI init 创建。\n\n"
            f"通用 code-arch 记忆仍使用 democode/phase6/instances。\n",
            encoding="utf-8",
        )
    env_example = DEMOCODE_ROOT / ".env.example"
    if env_example.exists() and not (ws / ".env.example").exists():
        shutil.copy2(env_example, ws / ".env.example")
    print(f"✓ init workspace → {ws}")
    print(f"  config → {ws / 'workspace.toml'}")
    return 0


def cmd_init_app(args: argparse.Namespace) -> int:
    name = args.name
    ws = Path(args.workspace).resolve()
    if name != "meeting_order":
        print(f"目前仅支持 init-app meeting_order，收到: {name}", file=sys.stderr)
        print("  提示: 应用脚手架由 ifclubdemo 维护，请使用：", file=sys.stderr)
        print("    cd ifclubdemo && python cli.py init-app meeting_order", file=sys.stderr)
        return 2
    # 委托 ifclubdemo CLI 生成脚手架（scaffold 由 ifclubdemo 维护，避免跨包复制漂移）
    ifclub_cli = DEMOCODE_ROOT / "ifclubdemo" / "cli.py"
    if not ifclub_cli.exists():
        print(f"找不到 ifclubdemo CLI: {ifclub_cli}", file=sys.stderr)
        return 2
    rc = subprocess.run(
        [sys.executable, str(ifclub_cli), "init-app", "meeting_order", "--workspace", str(ws)],
        cwd=str(DEMOCODE_ROOT),
    ).returncode
    if rc == 0:
        print(f"  下一步: 编辑 {ws / 'docs' / 'business_brief.md'}")
        print(f"  然后: python cli.py inject docs/business_brief.md --workspace {ws}")
    return rc


def cmd_inject(args: argparse.Namespace) -> int:
    ws = Path(args.workspace).resolve()
    cfg = WorkspaceConfig.load(ws)
    brief = Path(args.file)
    if not brief.is_absolute():
        # 相对 workspace 或 cwd
        cand = ws / brief
        brief = cand if cand.exists() else Path(args.file).resolve()
    if not brief.exists():
        print(f"找不到业务说明: {brief}", file=sys.stderr)
        return 2
    memory_dir = ws / cfg.domain_memory_dir
    report = inject_business_brief(brief, memory_dir, dry_run=args.dry_run)
    mode = "dry-run" if args.dry_run else "written"
    print(f"✓ inject ({mode}) source={brief}")
    print(f"  memory_dir={memory_dir}")
    print(f"  items={len(report.items)}")
    for it in report.items:
        print(f"  - {it.memory_id} [{it.object_type}] {it.title}")
    if not args.dry_run:
        print(f"  report → {memory_dir.parent / 'inject_report.json'}")
    return 0


def _build_coordinator(ws: Path, *, apply: bool, run_pytest: bool):
    from federated_graph import DomainConfig, FederatedGraph
    from harness.ep_coordinator import EPCoordinator
    from memory_injector import BudgetConfig

    cfg = WorkspaceConfig.load(ws)
    schema_root = PHASE6 / "schema"
    domain_memory = ws / cfg.domain_memory_dir
    # 若 workspace 有领域记忆则以其作为业务域；否则仍挂 purchasing 示例域
    domain_configs = [
        DomainConfig(
            name="code-arch",
            instances_root=PHASE6 / "instances",
            schema_root=schema_root,
            budget=BudgetConfig(hot=350, warm=500, cold=0, reserve=150),
            priority=0,
        ),
    ]
    if domain_memory.exists() and any(domain_memory.rglob("*.md")):
        domain_configs.append(
            DomainConfig(
                name="purchasing",  # 复用现有 scope 域名，避免大改 scope
                instances_root=domain_memory,
                schema_root=schema_root,
                budget=BudgetConfig(hot=300, warm=200, cold=0, reserve=150),
                priority=1,
            )
        )
    else:
        domain_configs.append(
            DomainConfig(
                name="purchasing",
                instances_root=PHASE6 / "instances_purchasing",
                schema_root=schema_root,
                budget=BudgetConfig(hot=300, warm=200, cold=0, reserve=150),
                priority=1,
            )
        )

    fed = FederatedGraph(domain_configs)
    fed.load()
    return EPCoordinator(
        fed,
        domain_configs,
        workspace_root=ws,
        apply_enabled=apply,
        run_pytest=run_pytest and cfg.run_pytest,
        allowed_write_globs=cfg.allowed_write_globs,
        allowed_path_prefixes=tuple(cfg.allowed_path_prefixes),
    ), cfg


def cmd_run(args: argparse.Namespace) -> int:
    if args.no_llm:
        set_force_stub(True)
    ws = Path(args.workspace).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    if not (ws / "workspace.toml").exists():
        WorkspaceConfig(name=ws.name, root=ws).save()

    task_text = args.task
    if args.task_file:
        task_text = Path(args.task_file).read_text(encoding="utf-8")
    if not task_text:
        print("需要 --task 或 --task-file", file=sys.stderr)
        return 2

    from phase4.multi_agent_router import Task

    coordinator, _cfg = _build_coordinator(
        ws, apply=not args.no_apply, run_pytest=not args.no_pytest
    )
    task = Task(description=task_text, context={})
    if args.fix_mode:
        task.context["_fix_mode"] = True
        if args.files:
            task.context["_fix_files"] = [f.strip() for f in args.files.split(",") if f.strip()]
        feedback = ws / ".ontology_agent" / "last_verify.json"
        if args.from_verify and feedback.exists():
            task.context["_last_verify_feedback"] = feedback.read_text(encoding="utf-8")

    print("=" * 60)
    print(f"  democode CLI {'fix' if args.fix_mode else 'run'}")
    print(f"  workspace: {ws}")
    print(f"  LLM      : {llm_mode_label()}")
    print(f"  apply    : {not args.no_apply}")
    print("=" * 60)

    result = coordinator.run_ep(
        task,
        keywords=args.keywords.split(",") if args.keywords else None,
        dry_run=args.no_apply,
    )
    print("\n" + result.summary())

    # 持久化最近一次 verify 反馈，供 fix --from-verify
    fb = task.context.get("_last_verify_feedback")
    if fb:
        out = ws / ".ontology_agent" / "last_verify.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(fb, str):
            out.write_text(fb, encoding="utf-8")
        else:
            import json

            out.write_text(json.dumps(fb, ensure_ascii=False, indent=2), encoding="utf-8")

    return 0 if result.status == "completed" else 1


def cmd_fix(args: argparse.Namespace) -> int:
    args.fix_mode = True
    if not args.task and not args.from_verify:
        args.task = "修复最近一次验证失败的问题，尽量小改动"
    return cmd_run(args)


def cmd_verify(args: argparse.Namespace) -> int:
    ws = Path(args.workspace).resolve()
    cfg = WorkspaceConfig.load(ws)
    print(f"== verify {ws} ==")
    # compileall
    py_roots = []
    for cand in ("backend/src", "src", "."):
        p = ws / cand
        if p.exists():
            py_roots.append(p)
            break
    rc = 0
    if py_roots:
        r = subprocess.run(
            [sys.executable, "-m", "compileall", "-q", str(py_roots[0])],
            cwd=str(ws),
        )
        print(f"  compileall: {'ok' if r.returncode == 0 else 'FAIL'}")
        rc = r.returncode or rc
    # pytest
    cmd = cfg.test_cmd.split()
    if cmd[0] == "pytest":
        cmd = [sys.executable, "-m", "pytest", *cmd[1:]]
    r = subprocess.run(cmd, cwd=str(ws))
    print(f"  pytest: {'ok' if r.returncode in (0, 5) else 'FAIL'} (code={r.returncode})")
    if r.returncode not in (0, 5):
        rc = r.returncode
    return rc


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="democode-cli", description="Ontology-native coding CLI")
    sub = p.add_subparsers(dest="command", required=True)

    def add_ws(sp):
        sp.add_argument(
            "--workspace",
            default=str(_default_workspace()),
            help="工作区根目录",
        )

    sp = sub.add_parser("doctor", help="检查环境")
    add_ws(sp)
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("init", help="初始化通用 workspace")
    add_ws(sp)
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("init-app", help="生成应用脚手架")
    sp.add_argument("name", help="应用名，目前支持 meeting_order")
    add_ws(sp)
    sp.set_defaults(func=cmd_init_app)

    sp = sub.add_parser("inject", help="从业务说明生成领域记忆")
    sp.add_argument("file", help="业务说明 markdown 路径")
    sp.add_argument("--dry-run", action="store_true")
    add_ws(sp)
    sp.set_defaults(func=cmd_inject)

    def add_run_flags(sp):
        add_ws(sp)
        sp.add_argument("--task", default="", help="任务描述")
        sp.add_argument("--task-file", default="", help="任务文件")
        sp.add_argument("--keywords", default="", help="逗号分隔关键词")
        sp.add_argument("--no-llm", action="store_true")
        sp.add_argument("--no-apply", action="store_true", help="不落盘")
        sp.add_argument("--no-pytest", action="store_true")
        sp.add_argument("--files", default="", help="限定文件（fix）")
        sp.add_argument("--from-verify", action="store_true")
        sp.set_defaults(fix_mode=False)

    sp = sub.add_parser("run", help="跑单次 EP")
    add_run_flags(sp)
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("fix", help="增量修复现有代码")
    add_run_flags(sp)
    sp.set_defaults(func=cmd_fix, fix_mode=True)

    sp = sub.add_parser("verify", help="compile + pytest")
    add_ws(sp)
    sp.set_defaults(func=cmd_verify)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
