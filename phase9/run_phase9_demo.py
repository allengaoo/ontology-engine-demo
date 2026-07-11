#!/usr/bin/env python3
"""
Phase 9：Memory Prompt 流水线 + 多 EP 队列

  queue.run([EP-1, EP-2])：
    EP-1 → PromotionGate → writeback → SessionFlush → reload
    EP-2（依赖 EP-1）→ pre_run_hook 快照 Manifest → 真实 run
  验证：EP-2 的 Manifest 含 EP-1 晋升的 DEC/PAT。

隔离：base instances 复制到独立 workspace，写回不污染 phase6/instances。

运行：
  cd democode
  python3 phase9/run_phase9_demo.py --no-llm --dry-run
  python3 phase9/run_phase9_demo.py --no-llm
  python3 phase9/run_phase9_demo.py             # 真实 LLM（读 democode/.env，qwen3-32b）
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

from federated_graph import FederatedGraph  # noqa: E402
from ep_queue import EpQueue, EpQueueItem  # noqa: E402
from harness.ep_coordinator import (  # noqa: E402
    EPCoordinator,
    FederatedInjectorWrapper,
    PHASE8_DEFAULT_SCOPES,
)
from llm_chat import llm_mode_label, set_force_stub  # noqa: E402
from memory_actions import MemoryActions  # noqa: E402
from memory_ep_writeback import MemoryEPWriteback  # noqa: E402
from memory_prompt_builder import MemoryPromptBuilder  # noqa: E402
from ontology_registry import OntologyRegistry  # noqa: E402
from phase4.multi_agent_router import Task  # noqa: E402
from run_phase8_demo import SCENARIOS, build_domain_configs  # noqa: E402


def build_actions(domain_configs) -> dict:
    actions = {}
    for d in domain_configs:
        reg = OntologyRegistry(d.schema_root)
        actions[d.name] = MemoryActions(d.instances_root, reg)
    return actions


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


def preview(builder: MemoryPromptBuilder, task: Task, keywords: list, label: str) -> dict:
    scope = PHASE8_DEFAULT_SCOPES["BusinessStructureAgent"]
    result = builder.build(scope, task.description, keywords)
    print(f"\n[{label}] MemoryPromptBuilder")
    print(result.summary())
    ep_ids = result.ep_writeback_ids()
    print(f"  EP 写回 ids: {ep_ids}")
    return {"memory_ids": result.memory_ids, "ep_writeback_ids": ep_ids}


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 9 · Memory Prompt + EpQueue")
    parser.add_argument("--dry-run", action="store_true", help="writeback 不写盘")
    parser.add_argument("--no-llm", action="store_true", help="强制 stub")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="隔离目录（默认临时目录，跑完清理）",
    )
    args = parser.parse_args()
    if args.no_llm:
        set_force_stub(True)

    schema_root = PHASE6 / "schema"
    domain_configs = build_domain_configs(schema_root)

    tmp_ws = None
    if args.workspace:
        ws = args.workspace
    else:
        tmp_ws = tempfile.mkdtemp(prefix="phase9_")
        ws = Path(tmp_ws)
    isolate_instances(domain_configs, ws)
    print(f"  workspace（隔离，零污染）: {ws}")

    scenario = SCENARIOS["kafka_idempotent"]
    keywords = scenario["keywords"]

    fed = FederatedGraph(domain_configs)
    fed.load()
    coordinator = EPCoordinator(fed, domain_configs)
    builder = MemoryPromptBuilder(fed, domain_configs, coordinator.intent_router)
    ep_writeback = MemoryEPWriteback(build_actions(domain_configs))

    def reload_graph() -> None:
        # reload 后必须重建 coordinator 的 injector，否则 agent 仍读旧图（staleness 修复）
        fed.load()
        coordinator.fed_injector = FederatedInjectorWrapper(fed)
        coordinator._ensure_schema_windows()

    queue = EpQueue(
        coordinator,
        ep_writeback,
        reload_fn=reload_graph,
        primary_domain="purchasing",  # 写回落隔离的 purchasing 域
    )

    print("=" * 60)
    print("  Phase 9 · Memory Prompt 流水线 + 多 EP 队列")
    print(f"  LLM  : {llm_mode_label()}")
    print(f"  dry_run={args.dry_run}")
    print("=" * 60)

    task1 = Task(description=scenario["description"], user_id="phase9-ep1")
    task2 = Task(description=scenario["description"], user_id="phase9-ep2")

    before = preview(builder, task1, keywords, "写回前 / EP-1 视角")

    # 差分快照：EP-2 真正 run 之前（上游已 promote+reload）抓 Manifest
    snapshots: dict = {}

    def snapshot_before_ep2(item: EpQueueItem) -> None:
        if item.ep_label == "EP-2":
            snapshots["ep2"] = preview(
                builder, item.task, item.keywords, "写回后 / EP-2 入队前快照"
            )

    items = [
        EpQueueItem(ep_label="EP-1", task=task1, keywords=keywords),
        EpQueueItem(ep_label="EP-2", task=task2, keywords=keywords, depends_on="EP-1"),
    ]

    queue_result = queue.run(items, dry_run=args.dry_run, pre_run_hook=snapshot_before_ep2)
    print(f"\n{queue_result.summary()}")

    ep2_snap = snapshots.get("ep2", {"ep_writeback_ids": []})
    new_ids = set(ep2_snap["ep_writeback_ids"]) - set(before["ep_writeback_ids"])

    print("\n" + "=" * 60)
    if new_ids:
        print(f"✓ Phase 9 验收：EP-2 Manifest 可见 EP-1 晋升 → {sorted(new_ids)}")
    elif args.dry_run:
        written = queue_result.items[0].written_ids if queue_result.items else []
        print("○ dry-run：写回未落盘，Manifest 不变（预期）")
        print(f"  若真实写回，将产生：{written}")
    else:
        print("⚠ EP-2 Manifest 未检索到新写回（检查 keywords / tier / reload）")
    print("  [1] MemoryPromptBuilder 四段审计已打印")
    print("  [2] EpQueue：两个 EP 均入队；EP-1 PASS→promote→reload，EP-2 依赖满足后 run")
    print("  [3] EP-2 pre_run_hook 快照 Manifest 差分")
    print("=" * 60)

    # Compression 段真实演示：设跨域全局上限，观察裁剪（不影响上面的验收 build）
    capped = MemoryPromptBuilder(
        fed, domain_configs, coordinator.intent_router, global_token_cap=600
    )
    demo = capped.build(
        PHASE8_DEFAULT_SCOPES["BusinessStructureAgent"], task2.description, keywords
    )
    comp = next((s for s in demo.stages if s.name == "Compression"), None)
    print(
        f"\n[Compression 演示] 全局上限=600 → "
        f"dropped={len(demo.dropped_ids)} 最终 tokens="
        f"{demo.manifest.total_tokens if demo.manifest else 0}"
        + (f"\n  裁剪节点: {demo.dropped_ids}" if demo.dropped_ids else "")
        + (f"\n  {comp.notes}" if comp else "")
    )

    if tmp_ws:
        shutil.rmtree(tmp_ws, ignore_errors=True)


if __name__ == "__main__":
    main()
