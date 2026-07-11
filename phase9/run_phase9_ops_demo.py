#!/usr/bin/env python3
"""
Phase 9 / 045：多 EP 节奏下的记忆治理

验证目标：
  1. 两个 EP 入队执行；
  2. 每次 reload 后可以读取健康快照；
  3. 队列空闲时运行 GC dry-run，不写盘、不污染主 instances。

运行：
  cd democode
  python3 phase9/run_phase9_ops_demo.py --no-llm
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

DEMOCODE_ROOT = Path(__file__).parent.parent
PHASE6 = DEMOCODE_ROOT / "phase6"
PHASE7 = DEMOCODE_ROOT / "phase7"
PHASE8 = DEMOCODE_ROOT / "phase8"
PHASE9 = Path(__file__).parent

sys.path.insert(0, str(PHASE6))
sys.path.insert(0, str(PHASE7))
sys.path.insert(0, str(PHASE8))
sys.path.insert(0, str(DEMOCODE_ROOT))
sys.path.append(str(PHASE9))

from ep_queue import EpQueue, EpQueueItem  # noqa: E402
from federated_graph import FederatedGraph  # noqa: E402
from harness.ep_coordinator import EPCoordinator, FederatedInjectorWrapper  # noqa: E402
from llm_chat import llm_mode_label, set_force_stub  # noqa: E402
from memory_actions import MemoryActions  # noqa: E402
from memory_ep_writeback import MemoryEPWriteback  # noqa: E402
from memory_ops import QueueMemoryOps  # noqa: E402
from ontology_registry import OntologyRegistry  # noqa: E402
from phase4.multi_agent_router import Task  # noqa: E402
from run_phase8_demo import SCENARIOS, build_domain_configs  # noqa: E402


def isolate_instances(domain_configs, ws: Path) -> None:
    ws.mkdir(parents=True, exist_ok=True)
    for d in domain_configs:
        src = Path(d.instances_root)
        dst = ws / d.name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst) if src.exists() else dst.mkdir(parents=True)
        d.instances_root = dst


def build_actions(domain_configs) -> dict:
    actions = {}
    for d in domain_configs:
        actions[d.name] = MemoryActions(
            d.instances_root, OntologyRegistry(d.schema_root)
        )
    return actions


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 9 / 045 · queue memory ops")
    parser.add_argument("--no-llm", action="store_true", help="强制 stub")
    parser.add_argument("--workspace", type=Path, default=None, help="隔离目录")
    args = parser.parse_args()
    if args.no_llm:
        set_force_stub(True)

    tmp_ws = None
    ws = args.workspace
    if ws is None:
        tmp_ws = tempfile.mkdtemp(prefix="phase9_ops_")
        ws = Path(tmp_ws)

    domain_configs = build_domain_configs(PHASE6 / "schema")
    isolate_instances(domain_configs, ws)
    actions = build_actions(domain_configs)

    fed = FederatedGraph(domain_configs)
    fed.load()
    coordinator = EPCoordinator(fed, domain_configs)
    ep_writeback = MemoryEPWriteback(actions)
    ops = QueueMemoryOps(fed, actions)
    reload_health = []

    def reload_graph() -> None:
        fed.load()
        coordinator.fed_injector = FederatedInjectorWrapper(fed)
        coordinator._ensure_schema_windows()
        reload_health.extend(ops.after_reload_health())

    queue = EpQueue(
        coordinator,
        ep_writeback,
        reload_fn=reload_graph,
        primary_domain="purchasing",
    )

    scenario = SCENARIOS["kafka_idempotent"]
    items = [
        EpQueueItem(
            ep_label="EP-1",
            task=Task(description=scenario["description"], user_id="phase9-ops-1"),
            keywords=scenario["keywords"],
        ),
        EpQueueItem(
            ep_label="EP-2",
            task=Task(description=scenario["description"], user_id="phase9-ops-2"),
            keywords=scenario["keywords"],
            depends_on="EP-1",
        ),
    ]

    print("=" * 60)
    print("  Phase 9 / 045 · 队列节奏下的记忆治理")
    print(f"  LLM  : {llm_mode_label()}")
    print(f"  workspace: {ws}")
    print("=" * 60)

    queue_result = queue.run(items, dry_run=False)
    print("\n" + queue_result.summary())

    report = ops.run_after_queue()
    print("\n[reload 后健康快照]")
    for h in reload_health[-4:]:
        print("  " + h.summary())
    print("\n[queue idle ops]")
    print(report.summary())

    if queue_result.reloads >= 2 and report.health and report.gc:
        print("\n✓ 记忆治理验证通过：reload 后可观测，queue idle 可跑 GC dry-run")
    else:
        raise SystemExit("记忆治理验证失败：缺少 reload/health/gc 输出")

    if tmp_ws:
        shutil.rmtree(tmp_ws, ignore_errors=True)


if __name__ == "__main__":
    main()
