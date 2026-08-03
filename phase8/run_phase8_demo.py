#!/usr/bin/env python3
"""
Phase 8 演示：Harness + Ontology + 双 Agent（BSA + CA）

  IntentRouter → inject(BSA) → StructurePlan → AtomicityCheck
    → inject(CA) × Unit → VerifyGate → writeback(DecisionRecord)

运行：
  cd democode
  python3 phase8/run_phase8_demo.py --dry-run
  python3 phase8/run_phase8_demo.py --scenario kafka_idempotent --dry-run
  python3 phase8/run_phase8_demo.py --scenario impl_fail --dry-run
  python3 phase8/run_phase8_demo.py --scenario struct_fail --dry-run
"""

from __future__ import annotations

import argparse
import sys
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
from harness.ep_coordinator import EPCoordinator  # noqa: E402
from memory_injector import BudgetConfig  # noqa: E402
from roles_loader import load_scopes_from_dir  # noqa: E402

from llm_chat import llm_mode_label, set_force_stub  # noqa: E402

from phase4.multi_agent_router import Task  # noqa: E402


SCENARIOS = {
    "kafka_idempotent": {
        "description": (
            "修复 procurement_service.py Kafka 消息重复触发采购订单问题，"
            "需满足供应商合规约束与 code-arch 分层"
        ),
        "keywords": [
            "idempotency", "kafka", "procurement", "采购",
            "compliance", "architecture",
        ],
        "context": {},
    },
    "impl_fail": {
        "description": "同上（demo：首轮 CA 违反 ARCH-001，VerifyGate FAIL_IMPL 后重试）",
        "keywords": ["idempotency", "kafka", "procurement", "architecture"],
        "context": {"_force_impl_fail": True},
    },
    "struct_fail": {
        "description": "同上（demo：首轮 BSA 路径越界，AtomicityCheck FAIL_STRUCT 后 replan）",
        "keywords": ["idempotency", "kafka", "procurement"],
        "context": {"_force_struct_fail": True},
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
            budget=BudgetConfig(hot=300, warm=200, cold=0, reserve=150),
            priority=1,
        ),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 8 · Harness + BSA + CA")
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS.keys()),
        default="kafka_idempotent",
        help="演示场景",
    )
    parser.add_argument("--dry-run", action="store_true", help="writeback 不写盘")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="强制 stub，不调用大模型（离线演示）",
    )
    parser.add_argument("--reload-roles", action="store_true", help="从 roles/*.toml 加载 scope")
    parser.add_argument("--resume", metavar="EP_ID", help="从 DagState checkpoint 续跑")
    parser.add_argument(
        "--workspace",
        default=str(DEMOCODE_ROOT / "workspace" / "phase8_app"),
        help="代码落盘目录（非 --dry-run 时生效）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Verify 通过后落盘（默认 dry-run 不落盘；加 --apply 且去掉 --dry-run）",
    )
    args = parser.parse_args()
    if args.no_llm:
        set_force_stub(True)

    schema_root = PHASE6 / "schema"
    domain_configs = build_domain_configs(schema_root)
    scenario = SCENARIOS[args.scenario]

    fed = FederatedGraph(domain_configs)
    counts = fed.load()
    print("=" * 60)
    print("  Phase 8 · Harness + Ontology + BSA/CA")
    print(f"  场景: {args.scenario}")
    print(f"  LLM  : {llm_mode_label()}")
    print("=" * 60)
    for d, n in counts.items():
        print(f"  域={d:<14} 节点数={n}")

    scope_registry = None
    if args.reload_roles:
        print("\n── 从 roles/*.toml 加载 scope ──────────────")
        scope_registry = load_scopes_from_dir(PHASE8 / "roles")

    apply_enabled = bool(args.apply) and not args.dry_run
    coordinator = EPCoordinator(
        fed,
        domain_configs,
        scope_registry=scope_registry,
        workspace_root=Path(args.workspace),
        apply_enabled=apply_enabled,
        run_pytest=apply_enabled,
    )
    task = Task(description=scenario["description"], user_id="demo-001")
    task.context = dict(scenario.get("context", {}))

    result = coordinator.run_ep(
        task,
        keywords=scenario["keywords"],
        dry_run=args.dry_run or not apply_enabled,
        ep_id=args.resume,
        resume=bool(args.resume),
    )

    print(f"\n{result.summary()}\n")
    print("=" * 60)
    print(f"  完成 status={result.status} ep_id={result.ep_id}")
    print("=" * 60)


if __name__ == "__main__":
    main()
