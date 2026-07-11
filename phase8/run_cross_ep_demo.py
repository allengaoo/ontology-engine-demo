#!/usr/bin/env python3
"""
Phase 8 P1：跨 EP 记忆与写回演示

  EP-1：run_ep → PromotionGate → writeback(DEC + Plan 模板) → session flush
  EP-2：同类任务 → inject 含 EP-1 写回 → 对比 manifest

运行：
  cd democode
  python3 phase8/run_cross_ep_demo.py --no-llm --dry-run
  python3 phase8/run_cross_ep_demo.py --no-llm          # 真实写回 instances
  python3 phase8/run_cross_ep_demo.py --no-llm --workspace ./workspace/cross_ep
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

DEMOCODE_ROOT = Path(__file__).parent.parent
PHASE6 = DEMOCODE_ROOT / "phase6"
PHASE7 = DEMOCODE_ROOT / "phase7"
PHASE8 = Path(__file__).parent
sys.path.insert(0, str(PHASE6))
sys.path.insert(0, str(PHASE7))
sys.path.insert(0, str(PHASE8))
sys.path.insert(0, str(DEMOCODE_ROOT))

from federated_graph import DomainConfig, FederatedGraph  # noqa: E402
from harness.ep_coordinator import EPCoordinator, FederatedInjectorWrapper  # noqa: E402
from harness.ep_promotion import EPPromotionGate  # noqa: E402
from harness.session_flush import SessionFlush  # noqa: E402
from memory_ep_writeback import MemoryEPWriteback  # noqa: E402
from memory_injector import BudgetConfig  # noqa: E402
from memory_actions import MemoryActions  # noqa: E402
from ontology_registry import OntologyRegistry  # noqa: E402
from llm_chat import llm_mode_label, set_force_stub  # noqa: E402

from phase4.multi_agent_router import Task  # noqa: E402
from run_phase8_demo import build_domain_configs, SCENARIOS  # noqa: E402


def isolate_instances(domain_configs, ws: Path) -> None:
    """把各域 base instances 复制进 workspace，写回全部落隔离目录，零污染。"""
    ws.mkdir(parents=True, exist_ok=True)
    for d in domain_configs:
        src = Path(d.instances_root)
        dst = ws / d.name
        if dst.exists():
            shutil.rmtree(dst)
        if src.exists():
            shutil.copytree(src, dst)
        else:
            dst.mkdir(parents=True, exist_ok=True)
        d.instances_root = dst


def build_actions(domain_configs) -> dict:
    actions = {}
    for d in domain_configs:
        reg = OntologyRegistry(d.schema_root)
        actions[d.name] = MemoryActions(d.instances_root, reg)
    return actions


def inject_preview(coordinator: EPCoordinator, task: Task, keywords: list) -> dict:
    """BSA scope inject 预览（不跑 Agent）。"""
    coordinator._ensure_schema_windows()
    manifest = coordinator._inject_for_agent("BusinessStructureAgent", task, keywords)
    ids = coordinator._collect_memory_ids(manifest)
    ep_dec = [i for i in ids if i.startswith("DEC-EP") or i.startswith("BIZ-PAT-EP")]
    return {
        "total_memories": manifest.total_memories if manifest else 0,
        "total_tokens": manifest.total_tokens if manifest else 0,
        "memory_ids": ids,
        "ep_writeback_ids": ep_dec,
    }


def run_ep_with_promotion(
    coordinator: EPCoordinator,
    ep_writeback: MemoryEPWriteback,
    task: Task,
    keywords: list,
    dry_run: bool,
    label: str,
) -> dict:
    print(f"\n{'=' * 60}\n  {label}\n{'=' * 60}")
    result = coordinator.run_ep(task, keywords=keywords, dry_run=dry_run)

    # 从最后一轮 plan 重建 structure_plan 摘要（demo 从 turns 取）
    structure_plan = None
    last_plan_turn = next(
        (t for t in reversed(result.turns) if t.agent_name == "BusinessStructureAgent"),
        None,
    )

    promotion_gate = EPPromotionGate()
    session_flush = SessionFlush(coordinator.bg_store)
    pending = session_flush.pending_count

    # 从 coordinator 最后一次 BSA 输出重建较完整 plan — 简化用 ep result
    from agents.structure_plan import StructurePlan, PlanUnit, UnitKind
    exec_turns = [t for t in result.turns if t.phase.value == "execute"]
    if exec_turns:
        units = [
            PlanUnit(
                unit_id=t.step_label,
                kind=UnitKind.MODIFY,
                target_path=t.outcome.split("→")[-1].strip() if "→" in t.outcome else t.step_label,
                description=t.outcome,
            )
            for t in exec_turns
        ]
        structure_plan = StructurePlan(
            plan_id=f"plan-{result.ep_id}",
            action="apply_idempotency_pattern",
            units=units,
        )

    promo = promotion_gate.plan_promotion(
        result,
        structure_plan,
        verify_result=None,
        memory_ids=last_plan_turn.memory_ids if last_plan_turn else [],
        bg_pending_count=pending,
    )
    print(f"\n[PromotionGate]\n{promo.summary()}")

    written_ids = []
    for item in promo.shared_items():
        nid = ep_writeback.apply_item(
            item,
            task_description=task.description,
            dry_run=dry_run,
        )
        if nid:
            written_ids.append(nid)

    archive = session_flush.compress_turns(result.turns)
    flushed = session_flush.flush_ep_session(task)
    print(f"\n[SessionFlush] archive={archive[:120]}...")
    print(f"[SessionFlush] flushed bg_store entries={flushed}")

    return {
        "ep_id": result.ep_id,
        "status": result.status,
        "written_ids": written_ids,
        "promotion": promo,
        "result": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 8 P1 · 跨 EP 记忆与写回")
    parser.add_argument("--dry-run", action="store_true", help="writeback 不写盘")
    parser.add_argument("--no-llm", action="store_true", help="强制 stub")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="隔离目录（默认临时目录，跑完清理）；写回不污染 phase6/instances",
    )
    args = parser.parse_args()
    if args.no_llm:
        set_force_stub(True)

    schema_root = PHASE6 / "schema"
    domain_configs = build_domain_configs(schema_root)

    # 默认隔离：base instances 复制到 workspace，写回落隔离目录，零污染
    tmp_ws = None
    if args.workspace:
        ws = Path(args.workspace)
    else:
        tmp_ws = tempfile.mkdtemp(prefix="cross_ep_")
        ws = Path(tmp_ws)
    isolate_instances(domain_configs, ws)
    print(f"  workspace（隔离，零污染）: {ws}")

    scenario = SCENARIOS["kafka_idempotent"]
    task = Task(description=scenario["description"], user_id="cross-ep-demo")
    keywords = scenario["keywords"]

    fed = FederatedGraph(domain_configs)
    fed.load()
    coordinator = EPCoordinator(fed, domain_configs)
    ep_writeback = MemoryEPWriteback(build_actions(domain_configs))

    print("=" * 60)
    print("  Phase 8 P1 · 跨 EP 记忆与写回")
    print(f"  LLM  : {llm_mode_label()}")
    print(f"  dry_run={args.dry_run}")
    print("=" * 60)

    before = inject_preview(coordinator, task, keywords)
    print(f"\n[EP-2 预检] inject 预览（写回前）：memories={before['total_memories']} "
          f"ep_ids={before['ep_writeback_ids']}")

    ep1 = run_ep_with_promotion(
        coordinator, ep_writeback, task, keywords, args.dry_run, "EP-1 · 首次 Kafka 幂等"
    )

    if not args.dry_run and ep1["written_ids"]:
        print("\n[reload] 重新加载联邦图以检索 EP-1 写回...")
        # reload 后必须重建 coordinator injector，否则仍读旧图（staleness 修复）
        fed.load()
        coordinator.fed_injector = FederatedInjectorWrapper(fed)
        coordinator._ensure_schema_windows()

    task2 = Task(description=scenario["description"], user_id="cross-ep-demo-2")
    after = inject_preview(coordinator, task2, keywords)
    print(f"\n[EP-2 预检] inject 预览（写回后）：memories={after['total_memories']} "
          f"tokens≈{after['total_tokens']}")
    print(f"  全部 ids: {after['memory_ids'][:12]}{'...' if len(after['memory_ids']) > 12 else ''}")
    print(f"  EP 写回 ids: {after['ep_writeback_ids']}")

    new_ids = set(after["ep_writeback_ids"]) - set(before["ep_writeback_ids"])
    if new_ids:
        print(f"\n✓ 跨 EP 闭环：EP-2 inject 可见 EP-1 写回 → {sorted(new_ids)}")
    elif args.dry_run:
        print("\n○ dry-run 模式：写回未落盘，EP-2 inject 不变（预期行为）")
        print(f"  若真实写回，将产生：{ep1['written_ids']}")
    else:
        print("\n⚠ EP-2 inject 未检索到新写回节点（检查 keywords / tier / reload）")

    print("\n" + "=" * 60)
    print(f"  EP-1 status={ep1['status']} written={ep1['written_ids']}")
    print("=" * 60)

    if tmp_ws:
        shutil.rmtree(tmp_ws, ignore_errors=True)


if __name__ == "__main__":
    main()
