#!/usr/bin/env python3
"""
Phase 7 演示：Memory-Aware Multi-Agent

  IntentAgent → OntologyAgent → SimAgent [→ CoderAgent]
  每步：AgentMemoryScope → IntentRouter → FederatedInjector → execute → writeback

运行：
  cd democode
  python3 phase7/run_multi_agent_memory_demo.py
  python3 phase7/run_multi_agent_memory_demo.py --with-agents
  python3 phase7/run_multi_agent_memory_demo.py --with-agents --dry-run
  python3 phase7/run_multi_agent_memory_demo.py --plan
  python3 phase7/run_multi_agent_memory_demo.py --full --dry-run
  python3 phase7/run_multi_agent_memory_demo.py --full --scenario threshold --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEMOCODE_ROOT = Path(__file__).parent.parent
PHASE6 = DEMOCODE_ROOT / "phase6"
PHASE7 = Path(__file__).parent
sys.path.insert(0, str(PHASE6))
sys.path.insert(0, str(PHASE7))
sys.path.insert(0, str(DEMOCODE_ROOT))

from federated_graph import DomainConfig, FederatedGraph  # noqa: E402
from memory_aware_coordinator import MemoryAwareCoordinator  # noqa: E402
from memory_injector import BudgetConfig  # noqa: E402

from phase4.intent_agent import IntentAgent  # noqa: E402
from phase4.multi_agent_router import MultiAgentRouter, Task  # noqa: E402
from phase4.ontology_agent import OntologyAgent  # noqa: E402
from phase4.sim_agent import SimAgent  # noqa: E402
from coder_agent import CoderAgent  # noqa: E402


SCENARIOS = {
    "procurement": {
        "description": (
            "修复 procurement_service.py Kafka 消息重复触发采购订单问题，"
            "需满足供应商合规约束"
        ),
        "keywords": [
            "idempotency", "kafka", "procurement", "采购",
            "compliance", "supplier", "vendor",
        ],
    },
    "threshold": {
        "description": "将供应商认证有效期阈值从30天调整为15天，确保供应商合规",
        "keywords": ["阈值", "调整", "30", "15", "compliance", "supplier", "certification"],
    },
}


def build_domain_configs(schema_root: Path) -> list:
    return [
        DomainConfig(
            name="code-arch",
            instances_root=PHASE6 / "instances",
            schema_root=schema_root,
            budget=BudgetConfig(hot=350, warm=500, cold=0, reserve=150),
            priority=0,
        ),
        DomainConfig(
            name="purchasing",
            instances_root=PHASE6 / "instances_purchasing",
            schema_root=schema_root,
            budget=BudgetConfig(hot=300, warm=200, cold=0, reserve=100),
            priority=1,
        ),
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--with-agents",
        action="store_true",
        help="注入后调用 Phase 4 Agent + writeback",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="P1 完整 DAG：Sim 制衡重试 + CoderAgent",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Plan Mode：输出各 Agent scope + manifest 预览",
    )
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS.keys()),
        default="procurement",
        help="演示场景：procurement（Kafka 幂等）或 threshold（023 制衡）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="writeback 不写盘",
    )
    args = parser.parse_args()

    schema_root = PHASE6 / "schema"
    domain_configs = build_domain_configs(schema_root)
    scenario = SCENARIOS[args.scenario]

    fed = FederatedGraph(domain_configs)
    counts = fed.load()
    print("=" * 60)
    print("  Phase 7 · Memory-Aware Multi-Agent")
    print(f"  场景: {args.scenario}")
    print("=" * 60)
    for d, n in counts.items():
        print(f"  域={d:<14} 节点数={n}")

    task = Task(description=scenario["description"], user_id="demo-001")
    keywords = scenario["keywords"]

    plan_dir = DEMOCODE_ROOT / "workspace" / "plans"
    coordinator = MemoryAwareCoordinator(fed, domain_configs, plan_dir=plan_dir)

    if args.plan:
        print("\n" + coordinator.plan(task, keywords, include_coder=True))
        return

    router = None
    if args.with_agents or args.full:
        router = MultiAgentRouter(memory_dir=str(DEMOCODE_ROOT / "memory"))
        router.register_agent("IntentAgent", IntentAgent())
        router.register_agent("OntologyAgent", OntologyAgent())
        router.register_agent("SimAgent", SimAgent())
        if args.full:
            router.register_agent("CoderAgent", CoderAgent())

    result = coordinator.run(
        task,
        keywords=keywords,
        inject_only=not (args.with_agents or args.full),
        router=router,
        dry_run=args.dry_run,
        full_dag=args.full,
    )

    print(f"\n{result.summary()}\n")
    print("─" * 50)
    print("  各 Agent 回合明细")
    print("─" * 50)
    for turn in result.turns:
        print(f"\n  ▶ {turn.agent_name}" + (f" [{turn.step_label}]" if turn.step_label else ""))
        print(f"    scope : {turn.scope.summary()}")
        print(f"    route : intent={turn.route.intent.value} domains={turn.route.domains}")
        if turn.manifest:
            for dom, m in turn.manifest.domain_manifests.items():
                print(f"    inject[{dom}]: {m.memory_ids}  tokens≈{m.estimated_tokens}")
        if turn.agent_output:
            print(f"    output: status={turn.agent_output.status}")
            if turn.agent_output.reason:
                print(f"    reason: {turn.agent_output.reason[:80]}")
        if turn.writeback_id:
            print(f"    writeback: {turn.writeback_id}")
        if turn.wake_mode:
            print(f"    wake: {turn.wake_mode.value}")

    print("\n" + "=" * 60)
    if args.full:
        mode = "full-dag" + ("-dry-run" if args.dry_run else "")
    elif args.with_agents:
        mode = "with-agents" + ("-dry-run" if args.dry_run else "")
    else:
        mode = "inject-only"
    print(f"  完成（mode={mode} status={result.status}）")
    print("=" * 60)


if __name__ == "__main__":
    main()
