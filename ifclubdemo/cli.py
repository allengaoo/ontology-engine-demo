#!/usr/bin/env python3
"""
ifclubdemo CLI — 动态本体 + 多智能体 + 小模型编码工具

  python cli.py doctor
  python cli.py init-app meeting_order
  python cli.py inject docs/business_brief.md
  python cli.py inject-arch docs/architecture_brief.md
  python cli.py memory list
  python cli.py run --task "实现冲突检测"
  python cli.py fix --from-verify
  python cli.py verify
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

IFCLUB_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(IFCLUB_ROOT))

from env_bootstrap import (  # noqa: E402
    IFCLUB_ROOT as _ROOT,
    default_app_name,
    default_app_workspace,
    load_env,
    workspace_root,
)
from cli_support.inject_arch import inject_architecture_brief  # noqa: E402
from cli_support.inject_brief import inject_business_brief  # noqa: E402
from cli_support.scaffold_meeting_order import scaffold_meeting_order  # noqa: E402
from agents.coding_agent import allow_stub  # noqa: E402
from llm_chat import (  # noqa: E402
    is_llm_available,
    llm_mode_label,
    resolve_llm_model,
    set_force_stub,
)
from workspace_config import WorkspaceConfig  # noqa: E402


# 启动即加载 .env（LLM + WORKSPACE）
_LOADED_ENV = load_env()


def _resolve_workspace(args: argparse.Namespace) -> Path:
    """--workspace 优先；否则 $IFCLUB_WORKSPACE/$IFCLUB_APP。"""
    if getattr(args, "workspace", None):
        return Path(args.workspace).expanduser().resolve()
    return default_app_workspace().resolve()


def cmd_doctor(args: argparse.Namespace) -> int:
    ws = _resolve_workspace(args)
    print("== doctor ==")
    print(f"  ifclubdemo : {IFCLUB_ROOT}")
    print(f"  .env       : {_LOADED_ENV} exists={_LOADED_ENV.exists()}")
    print(f"  WORKSPACE  : {workspace_root()}")
    print(f"  APP        : {default_app_name()} → {ws}")
    print(f"  app exists : {ws.exists()}")
    print(f"  LLM        : {llm_mode_label()}")
    print(f"  model id   : {resolve_llm_model()}")
    print(f"  API key    : {'yes' if is_llm_available() else 'no'}")
    print(f"  allow_stub : {allow_stub()} (DEMOCODE_ALLOW_STUB)")
    if not is_llm_available() and not allow_stub():
        print("  ⚠ 无 API key 且 stub 禁用：run/fix 将失败")
    cfg_path = ws / "workspace.toml"
    print(f"  workspace.toml: {'yes' if cfg_path.exists() else 'no'}")
    if cfg_path.exists():
        cfg = WorkspaceConfig.load(ws)
        print(f"  app_entry  : {cfg.app_entry or '-'}")
        print(f"  test_cmd   : {cfg.test_cmd}")
        mem = ws / cfg.domain_memory_dir
        n = len(list(mem.rglob("*.md"))) if mem.exists() else 0
        print(f"  domain mem : {mem} ({n} files)")
        arch = ws / cfg.arch_memory_dir
        na = len(list(arch.rglob("*.md"))) if arch.exists() else 0
        if na:
            print(f"  arch mem   : {arch} ({na} files)")
        else:
            seed = IFCLUB_ROOT / "instances"
            ns = len(list(seed.rglob("*.md"))) if seed.exists() else 0
            print(f"  arch mem   : (fallback) {seed} ({ns} files)")
    for mod in ("openai", "fastapi", "pytest"):
        try:
            __import__(mod)
            print(f"  py:{mod}: ok")
        except ImportError:
            print(f"  py:{mod}: missing")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    ws = _resolve_workspace(args)
    ws.mkdir(parents=True, exist_ok=True)
    cfg = WorkspaceConfig(name=ws.name, root=ws)
    cfg.save()
    (ws / "src").mkdir(exist_ok=True)
    (ws / "tests").mkdir(exist_ok=True)
    (ws / ".ontology_agent" / "memory").mkdir(parents=True, exist_ok=True)
    (ws / ".ontology_agent" / "arch_memory").mkdir(parents=True, exist_ok=True)
    (ws / ".ontology_agent" / "backup").mkdir(parents=True, exist_ok=True)
    readme = ws / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# {ws.name}\n\n由 ifclubdemo CLI init 创建。\n\n"
            f"## 两条初始记忆\n\n"
            f"- 业务：`docs/business_brief.md` → `python cli.py inject` → `.ontology_agent/memory/`\n"
            f"- 架构：`docs/architecture_brief.md` → `python cli.py inject-arch` → `.ontology_agent/arch_memory/`\n"
            f"  （未 inject-arch 时回退包内 `ifclubdemo/instances/`）\n",
            encoding="utf-8",
        )
    print(f"✓ init workspace → {ws}")
    print(f"  config → {ws / 'workspace.toml'}")
    return 0


def cmd_init_app(args: argparse.Namespace) -> int:
    name = args.name
    if getattr(args, "workspace", None):
        ws = Path(args.workspace).expanduser().resolve()
    else:
        ws = default_app_workspace(name).resolve()
    if name == "meeting_order":
        root = scaffold_meeting_order(ws)
    else:
        print(
            f"目前仅支持 init-app meeting_order，收到: {name}",
            file=sys.stderr,
        )
        return 2
    print(f"✓ init-app {name} → {root}")
    print(f"  业务说明: {root / 'docs' / 'business_brief.md'} → inject")
    print(f"  架构说明: {root / 'docs' / 'architecture_brief.md'} → inject-arch")
    print(
        f"  下一步:\n"
        f"    python cli.py inject docs/business_brief.md --workspace {root}\n"
        f"    python cli.py inject-arch docs/architecture_brief.md --workspace {root}"
    )
    return 0


def cmd_inject(args: argparse.Namespace) -> int:
    ws = _resolve_workspace(args)
    cfg = WorkspaceConfig.load(ws)
    brief = Path(args.file)
    if not brief.is_absolute():
        cand = ws / brief
        brief = cand if cand.exists() else (Path.cwd() / args.file).resolve()
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
        print(f"  说明文档 → {IFCLUB_ROOT / 'docs' / 'BUSINESS_MEMORY.md'}")
    return 0


def cmd_inject_arch(args: argparse.Namespace) -> int:
    ws = _resolve_workspace(args)
    cfg = WorkspaceConfig.load(ws)
    brief = Path(args.file)
    if not brief.is_absolute():
        cand = ws / brief
        brief = cand if cand.exists() else (Path.cwd() / args.file).resolve()
    if not brief.exists():
        print(f"找不到架构说明: {brief}", file=sys.stderr)
        return 2
    memory_dir = ws / cfg.arch_memory_dir
    report = inject_architecture_brief(brief, memory_dir, dry_run=args.dry_run)
    mode = "dry-run" if args.dry_run else "written"
    print(f"✓ inject-arch ({mode}) source={brief}")
    print(f"  arch_memory_dir={memory_dir}")
    print(f"  items={len(report.items)}")
    for it in report.items:
        print(f"  - {it.memory_id} [{it.object_type}] {it.title}")
    if not args.dry_run:
        print(f"  report → {memory_dir.parent / 'inject_arch_report.json'}")
        print(f"  说明文档 → {IFCLUB_ROOT / 'docs' / 'ARCHITECTURE_MEMORY.md'}")
    return 0


def _print_memory_files(root: Path, label: str) -> None:
    print(f"\n── {label} → {root}")
    if not root.exists():
        print("  （目录不存在）")
        return
    files = sorted(root.rglob("*.md"))
    if not files:
        print("  （空）")
        return
    for f in files:
        head = f.read_text(encoding="utf-8")[:400]
        mid = title = otype = ""
        for line in head.splitlines():
            if line.startswith("id:"):
                mid = line.split(":", 1)[1].strip()
            elif line.startswith("title:"):
                title = line.split(":", 1)[1].strip()
            elif line.startswith("object_type:"):
                otype = line.split(":", 1)[1].strip()
        print(f"  - {f.relative_to(root)} | {mid or '?'} [{otype}] {title}")


def cmd_memory_list(args: argparse.Namespace) -> int:
    """列出业务记忆 + 架构记忆（工作区优先，否则包内种子）。"""
    ws = _resolve_workspace(args)
    cfg = WorkspaceConfig.load(ws) if (ws / "workspace.toml").exists() else None
    print("== memory list ==")
    print(f"  workspace: {ws}")

    domain_dir = ws / (
        cfg.domain_memory_dir if cfg else ".ontology_agent/memory"
    )
    _print_memory_files(domain_dir, "业务记忆（domain / inject）")
    if not domain_dir.exists() or not any(domain_dir.rglob("*.md")):
        print("  提示: python cli.py inject docs/business_brief.md")
    else:
        report = domain_dir.parent / "inject_report.json"
        if report.exists():
            print(f"  inject_report: {report}")

    arch_ws = ws / (cfg.arch_memory_dir if cfg else ".ontology_agent/arch_memory")
    arch_seed = IFCLUB_ROOT / "instances"
    if arch_ws.exists() and any(arch_ws.rglob("*.md")):
        _print_memory_files(arch_ws, "架构记忆（code-arch / inject-arch，工作区）")
        report = arch_ws.parent / "inject_arch_report.json"
        if report.exists():
            print(f"  inject_arch_report: {report}")
    else:
        _print_memory_files(arch_seed, "架构记忆（code-arch / 包内种子，未 inject-arch）")
        print("  提示: python cli.py inject-arch docs/architecture_brief.md")

    print(f"\n说明: {IFCLUB_ROOT / 'docs' / 'BUSINESS_MEMORY.md'}")
    print(f"      {IFCLUB_ROOT / 'docs' / 'ARCHITECTURE_MEMORY.md'}")
    return 0


def _resolve_arch_instances(ws: Path, cfg: WorkspaceConfig) -> Path:
    """工作区 arch_memory 优先，否则包内精简 instances。"""
    arch_ws = ws / cfg.arch_memory_dir
    if arch_ws.exists() and any(arch_ws.rglob("*.md")):
        return arch_ws
    return IFCLUB_ROOT / "instances"


def _build_coordinator(ws: Path, *, apply: bool, run_pytest: bool):
    import os

    from federated_graph import DomainConfig, FederatedGraph
    from harness.ep_coordinator import EPCoordinator
    from memory_injector import BudgetConfig
    from memory_ops import QueueMemoryOps

    cfg = WorkspaceConfig.load(ws)
    schema_root = IFCLUB_ROOT / "schema"
    arch_root = _resolve_arch_instances(ws, cfg)
    domain_memory = ws / cfg.domain_memory_dir

    # cold>0 时冷记忆仍可进预算窗口（多会话重建演示冷热切换）
    cold_budget = int(os.environ.get("DEMOCODE_COLD_BUDGET", "0") or "0")

    domain_configs = [
        DomainConfig(
            name="code-arch",
            instances_root=arch_root,
            schema_root=schema_root,
            budget=BudgetConfig(hot=350, warm=500, cold=cold_budget, reserve=150),
            priority=0,
        ),
    ]
    # 业务域：仅工作区 memory；无 purchasing 包级 fallback
    if domain_memory.exists() and any(domain_memory.rglob("*.md")):
        domain_configs.append(
            DomainConfig(
                name="domain",
                instances_root=domain_memory,
                schema_root=schema_root,
                budget=BudgetConfig(hot=300, warm=200, cold=cold_budget, reserve=150),
                priority=1,
            )
        )
    else:
        print(
            "  ⚠ 未找到业务记忆（.ontology_agent/memory）。"
            " 建议先: python cli.py inject docs/business_brief.md"
        )

    fed = FederatedGraph(domain_configs)
    fed.load()
    print(f"  code-arch ← {arch_root}")
    if len(domain_configs) > 1:
        print(f"  domain    ← {domain_memory}")

    # EP 结束空闲 GC：DEMOCODE_GC_APPLY=1 落盘；DEMOCODE_GC_AGE_STEP 驱动衰减
    gc_apply = os.environ.get("DEMOCODE_GC_APPLY", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    age_step = float(os.environ.get("DEMOCODE_GC_AGE_STEP", "0") or "0")
    actions = {}
    from ontology_registry import OntologyRegistry
    from memory_actions import MemoryActions

    for d_cfg in domain_configs:
        actions[d_cfg.name] = MemoryActions(
            d_cfg.instances_root, OntologyRegistry(d_cfg.schema_root)
        )
    memory_ops = QueueMemoryOps(
        fed,
        actions,
        gc_dry_run=not gc_apply,
        age_step=age_step,
    )
    print(
        f"  memory_ops: gc_apply={gc_apply} age_step={age_step} cold_budget={cold_budget}"
    )

    return EPCoordinator(
        fed,
        domain_configs,
        workspace_root=ws,
        apply_enabled=apply,
        run_pytest=run_pytest and cfg.run_pytest,
        allowed_write_globs=cfg.allowed_write_globs,
        allowed_path_prefixes=tuple(cfg.allowed_path_prefixes),
        memory_ops=memory_ops,
    ), cfg


def cmd_run(args: argparse.Namespace) -> int:
    if args.no_llm:
        set_force_stub(True)
    ws = _resolve_workspace(args)
    ws.mkdir(parents=True, exist_ok=True)
    if not (ws / "workspace.toml").exists():
        WorkspaceConfig(name=ws.name, root=ws).save()

    task_text = args.task
    if args.task_file:
        task_text = Path(args.task_file).read_text(encoding="utf-8")
    if not task_text:
        print("需要 --task 或 --task-file", file=sys.stderr)
        return 2

    from core.task import Task

    coordinator, _cfg = _build_coordinator(
        ws, apply=not args.no_apply, run_pytest=not args.no_pytest
    )
    task = Task(description=task_text, context={})
    if getattr(args, "tests", ""):
        task.context["_pytest_paths"] = [
            t.strip() for t in args.tests.split(",") if t.strip()
        ]
    if args.fix_mode:
        task.context["_fix_mode"] = True
        if args.files:
            task.context["_fix_files"] = [
                f.strip() for f in args.files.split(",") if f.strip()
            ]
        feedback = ws / ".ontology_agent" / "last_verify.json"
        if args.from_verify and feedback.exists():
            raw = feedback.read_text(encoding="utf-8")
            try:
                task.context["_last_verify_feedback"] = json.loads(raw)
            except json.JSONDecodeError:
                task.context["_last_verify_feedback"] = {"detail": raw}

    print("=" * 60)
    print(f"  ifclubdemo {'fix' if args.fix_mode else 'run'}")
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

    fb = task.context.get("_last_verify_feedback")
    if fb:
        out = ws / ".ontology_agent" / "last_verify.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(fb, str):
            out.write_text(fb, encoding="utf-8")
        else:
            out.write_text(json.dumps(fb, ensure_ascii=False, indent=2), encoding="utf-8")

    return 0 if result.status == "completed" else 1


def cmd_fix(args: argparse.Namespace) -> int:
    args.fix_mode = True
    if not args.task and not args.from_verify:
        args.task = "修复最近一次验证失败的问题，尽量小改动"
    return cmd_run(args)


def cmd_verify(args: argparse.Namespace) -> int:
    import os

    ws = _resolve_workspace(args)
    cfg = WorkspaceConfig.load(ws)
    print(f"== verify {ws} ==")
    py_roots = []
    for cand in ("backend/src", "src", "."):
        p = ws / cand
        if p.exists():
            py_roots.append(p)
            break
    env = os.environ.copy()
    path_parts = []
    for cand in ("backend/src", "src"):
        p = ws / cand
        if p.is_dir():
            path_parts.append(str(p.resolve()))
    if path_parts:
        prev = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            path_parts + ([prev] if prev else [])
        )
        print(f"  PYTHONPATH+: {path_parts}")
    rc = 0
    if py_roots:
        r = subprocess.run(
            [sys.executable, "-m", "compileall", "-q", str(py_roots[0])],
            cwd=str(ws),
            env=env,
        )
        print(f"  compileall: {'ok' if r.returncode == 0 else 'FAIL'}")
        rc = r.returncode or rc
    cmd = cfg.test_cmd.split()
    if cmd[0] == "pytest":
        cmd = [sys.executable, "-m", "pytest", *cmd[1:]]
    tests = (getattr(args, "tests", "") or "").strip()
    if tests:
        # 分阶段：覆盖 workspace.toml 的默认测试路径
        paths = [t.strip() for t in tests.split(",") if t.strip()]
        cmd = [sys.executable, "-m", "pytest", "-q", *paths]
        print(f"  tests scoped: {paths}")
    r = subprocess.run(cmd, cwd=str(ws), env=env)
    print(f"  pytest: {'ok' if r.returncode in (0, 5) else 'FAIL'} (code={r.returncode})")
    if r.returncode not in (0, 5):
        rc = r.returncode
    return rc


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ifclubdemo", description="Ontology-native coding CLI")
    sub = p.add_subparsers(dest="command", required=True)

    def add_ws(sp, *, required_default: bool = False):
        # default=None → 使用 .env 中的 IFCLUB_WORKSPACE/IFCLUB_APP
        sp.add_argument(
            "--workspace",
            default=None,
            help="工作区根目录（默认: $IFCLUB_WORKSPACE/$IFCLUB_APP）",
        )

    sp = sub.add_parser("doctor", help="检查环境与 .env")
    add_ws(sp)
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("init", help="初始化通用 workspace")
    add_ws(sp)
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("init-app", help="生成应用脚手架")
    sp.add_argument("name", nargs="?", default=None, help="应用名，默认 $IFCLUB_APP / meeting_order")
    add_ws(sp)
    sp.set_defaults(func=lambda a: cmd_init_app(_with_app_name(a)))

    sp = sub.add_parser("inject", help="从业务说明生成领域记忆")
    sp.add_argument("file", help="业务说明 markdown 路径")
    sp.add_argument("--dry-run", action="store_true")
    add_ws(sp)
    sp.set_defaults(func=cmd_inject)

    sp = sub.add_parser("inject-arch", help="从架构说明生成工作区架构记忆")
    sp.add_argument("file", help="架构说明 markdown 路径")
    sp.add_argument("--dry-run", action="store_true")
    add_ws(sp)
    sp.set_defaults(func=cmd_inject_arch)

    mem = sub.add_parser("memory", help="记忆相关")
    mem_sub = mem.add_subparsers(dest="memory_cmd", required=True)
    sp = mem_sub.add_parser("list", help="列出业务记忆与架构记忆")
    add_ws(sp)
    sp.set_defaults(func=cmd_memory_list)

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
        sp.add_argument(
            "--tests",
            default="",
            help="限定 pytest 路径，逗号分隔（分阶段 EP 用，如 tests/meeting_order/test_rules.py）",
        )
        sp.set_defaults(fix_mode=False)

    sp = sub.add_parser("run", help="跑单次 EP（写代码）")
    add_run_flags(sp)
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("fix", help="增量修复现有代码")
    add_run_flags(sp)
    sp.set_defaults(func=cmd_fix, fix_mode=True)

    sp = sub.add_parser("verify", help="compile + pytest")
    add_ws(sp)
    sp.add_argument(
        "--tests",
        default="",
        help="限定 pytest 路径，逗号分隔（分阶段用）",
    )
    sp.set_defaults(func=cmd_verify)

    return p


def _with_app_name(args: argparse.Namespace) -> argparse.Namespace:
    if not args.name:
        args.name = default_app_name()
    return args


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
