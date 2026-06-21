"""
run_governance_demo.py — 记忆控制平面演示（Article 033）

演示顺序：
  ① GC 前健康报告
  ② 执行 GC（dry_run=True 展示决策，dry_run=False 写入文件）
  ③ GC 后重新加载 + 健康报告对比
  ④ 审计查询：查看 GC 操作记录
  ⑤ MemoryAdmin 批量弃用演示（dry_run）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from memory_actions import MemoryActions
from memory_admin import MemoryAdmin
from memory_gc import GCPolicy, MemoryGC
from memory_graph import MemoryGraph
from ontology_registry import OntologyRegistry

PHASE6_DIR = Path(__file__).parent
SCHEMA_DIR = PHASE6_DIR / "schema"
INSTANCES_DIR = PHASE6_DIR / "instances"


def _load_graph() -> tuple[MemoryGraph, MemoryActions]:
    registry = OntologyRegistry(SCHEMA_DIR)
    graph = MemoryGraph(INSTANCES_DIR, registry)
    graph.load()
    actions = MemoryActions(INSTANCES_DIR, registry)
    return graph, actions


def main():
    print("=" * 60)
    print("Phase 6 · 033  记忆控制平面演示")
    print("=" * 60)

    graph, actions = _load_graph()
    admin = MemoryAdmin(graph)

    # ── ① GC 前健康报告 ──────────────────────────────────────────
    print(f"\n加载节点: {len(graph.nodes)} 条")
    print("\n" + "─" * 50)
    print("① GC 前 · 健康报告")
    print("─" * 50)
    before = admin.health_report()
    print(before.summary())

    # ── ② dry_run GC 决策预览 ────────────────────────────────────
    print("\n" + "─" * 50)
    print("② GC 决策预览（dry_run=True）")
    print("   策略: decay_below=0.7  步长=0.1")
    print("         warm→cold  confidence<0.5")
    print("         cold→archived  confidence<0.3")
    print("         enable_stale_cleanup=True")
    print("─" * 50)
    dry_policy = GCPolicy(
        decay_below=0.7,
        decay_step=0.1,
        cold_below=0.5,
        archive_below=0.3,
        enable_stale_cleanup=True,
        dry_run=True,
    )
    dry_gc = MemoryGC(graph, dry_policy)
    dry_report = dry_gc.run_gc(actions)
    print(dry_report.summary())

    # ── ③ 实际执行 GC ────────────────────────────────────────────
    print("\n" + "─" * 50)
    print("③ 执行 GC（dry_run=False，写入文件）")
    print("─" * 50)
    real_policy = GCPolicy(
        decay_below=0.7,
        decay_step=0.1,
        cold_below=0.5,
        archive_below=0.3,
        enable_stale_cleanup=True,
        dry_run=False,
    )
    real_gc = MemoryGC(graph, real_policy)
    real_report = real_gc.run_gc(actions)
    print(real_report.summary())

    # ── ④ GC 后重新加载 + 健康对比 ───────────────────────────────
    print("\n" + "─" * 50)
    print("④ GC 后 · 重新加载 + 健康报告对比")
    print("─" * 50)
    graph2, actions2 = _load_graph()
    admin2 = MemoryAdmin(graph2)
    after = admin2.health_report()
    print(after.summary())

    print("\n  变化摘要:")
    for tier in set(list(before.by_tier.keys()) + list(after.by_tier.keys())):
        b = before.by_tier.get(tier, 0)
        a = after.by_tier.get(tier, 0)
        if b != a:
            print(f"    tier={tier}: {b} → {a}")
    for st in set(list(before.by_status.keys()) + list(after.by_status.keys())):
        b = before.by_status.get(st, 0)
        a = after.by_status.get(st, 0)
        if b != a:
            print(f"    status={st}: {b} → {a}")

    # ── ⑤ 审计查询 ───────────────────────────────────────────────
    print("\n" + "─" * 50)
    print("⑤ 审计查询：所有携带 gc_note 的节点")
    print("─" * 50)
    gc_nodes = admin2.audit_query(gc_note_contains="")
    gc_noted = [n for n in gc_nodes if n.meta.get("gc_note")]
    if gc_noted:
        for n in gc_noted:
            print(f"  {n.id:20s}  tier={n.tier:8s}  conf={n.confidence:.2f}  {n.meta.get('gc_note','')}")
    else:
        print("  （无 gc_note 节点）")

    # ── ⑥ 管理员批量操作演示 ─────────────────────────────────────
    print("\n" + "─" * 50)
    print("⑥ MemoryAdmin 批量弃用 archived 节点（dry_run=True）")
    print("─" * 50)
    candidates = admin2.bulk_deprecate_by_tier("archived", actions2, dry_run=True)
    if candidates:
        print(f"  候选节点（共 {len(candidates)} 条）: {candidates}")
        print("  dry_run=True，不实际写入")
    else:
        print("  当前无 archived tier active 节点")

    print("\n" + "=" * 60)
    print("控制平面演示完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
