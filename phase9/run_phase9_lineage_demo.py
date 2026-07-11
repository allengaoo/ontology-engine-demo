#!/usr/bin/env python3
"""
Phase 9 / 044：血统那一跳

验证目标：
  1. EP-1 PASS 后写回 DEC/PAT；
  2. EP-2 用窄关键词（ep-writeback）命中写回节点；
  3. LineageExpander 沿 derived_from 扩 1 跳，补回来源约束 / 模式。

运行：
  cd democode
  python3 phase9/run_phase9_lineage_demo.py --no-llm
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

from agent_memory_scope import AgentMemoryScope  # noqa: E402
from ep_queue import EpQueue, EpQueueItem  # noqa: E402
from federated_graph import FederatedGraph  # noqa: E402
from harness.ep_coordinator import EPCoordinator, FederatedInjectorWrapper  # noqa: E402
from lineage_expander import LineageExpander  # noqa: E402
from llm_chat import llm_mode_label, set_force_stub  # noqa: E402
from memory_actions import MemoryActions  # noqa: E402
from memory_ep_writeback import MemoryEPWriteback  # noqa: E402
from memory_prompt_builder import MemoryPromptBuilder  # noqa: E402
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
    parser = argparse.ArgumentParser(description="Phase 9 / 044 · lineage expansion")
    parser.add_argument("--no-llm", action="store_true", help="强制 stub")
    parser.add_argument("--workspace", type=Path, default=None, help="隔离目录")
    args = parser.parse_args()
    if args.no_llm:
        set_force_stub(True)

    tmp_ws = None
    ws = args.workspace
    if ws is None:
        tmp_ws = tempfile.mkdtemp(prefix="phase9_lineage_")
        ws = Path(tmp_ws)

    domain_configs = build_domain_configs(PHASE6 / "schema")
    isolate_instances(domain_configs, ws)

    fed = FederatedGraph(domain_configs)
    fed.load()
    coordinator = EPCoordinator(fed, domain_configs)
    builder = MemoryPromptBuilder(fed, domain_configs, coordinator.intent_router)
    ep_writeback = MemoryEPWriteback(build_actions(domain_configs))

    def reload_graph() -> None:
        fed.load()
        coordinator.fed_injector = FederatedInjectorWrapper(fed)
        coordinator._ensure_schema_windows()

    queue = EpQueue(
        coordinator,
        ep_writeback,
        reload_fn=reload_graph,
        primary_domain="purchasing",
    )

    scenario = SCENARIOS["kafka_idempotent"]
    task = Task(description=scenario["description"], user_id="phase9-lineage")

    print("=" * 60)
    print("  Phase 9 / 044 · 血统那一跳")
    print(f"  LLM  : {llm_mode_label()}")
    print(f"  workspace: {ws}")
    print("=" * 60)

    queue.run([
        EpQueueItem(
            ep_label="EP-1",
            task=task,
            keywords=scenario["keywords"],
        )
    ], dry_run=False)

    # 窄 scope：只用 ep-writeback 搜 DEC，避免常规关键词直接命中所有来源。
    narrow_scope = AgentMemoryScope(
        agent_name="LineageProbe",
        domains=["purchasing", "code-arch"],
        tiers=["warm", "hot"],
        read_layers=["decision", "pattern", "critical"],
        write_layers=[],
        budget_multiplier=1.0,
        concept_hints=[],
    )
    probe = builder.build(narrow_scope, task.description, ["ep-writeback"])
    print("\n[Probe Manifest]")
    print(probe.summary())
    print(f"  ids={probe.memory_ids}")

    expanded = LineageExpander(fed).expand(probe, max_added=6)
    print("\n" + expanded.summary())

    if expanded.seed_ids and (expanded.added_ids or expanded.already_present):
        print("\n✓ 血统扩展验证通过：derived_from 可从写回字段进入检索一跳")
    else:
        raise SystemExit("血统扩展验证失败：未找到 seed 或 derived_from")

    if tmp_ws:
        shutil.rmtree(tmp_ws, ignore_errors=True)


if __name__ == "__main__":
    main()
