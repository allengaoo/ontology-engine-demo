"""
run_intent_router_demo.py — 调度即查询演示（Article 034）

演示顺序：
  ① 四类任务的意图分类 + 路由决策
  ② 将路由配置接入 FederatedGraph 执行实际检索
  ③ 对比"无路由"（全量检索）与"有路由"（tier+domain 过滤）的结果差异
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from federated_graph import DomainConfig, FederatedGraph
from intent_router import IntentRouter

PHASE6_DIR = Path(__file__).parent
SCHEMA_DIR  = PHASE6_DIR / "schema"

DOMAIN_CONFIGS = [
    DomainConfig(
        name="code-arch",
        instances_root=PHASE6_DIR / "instances",
        schema_root=SCHEMA_DIR,
    ),
    DomainConfig(
        name="purchasing",
        instances_root=PHASE6_DIR / "instances_purchasing",
        schema_root=SCHEMA_DIR,
    ),
]

DEMO_TASKS = [
    {
        "task": "设计订单服务的分层架构，领域层不得依赖适配层",
        "keywords": ["architecture", "layering"],
    },
    {
        "task": "查询三个供应商的合规状态，是否满足 ISO-9001",
        "keywords": ["vendor", "compliance"],
    },
    {
        "task": "线上报错：EventSourcedRepository 抛出 NullPointerException",
        "keywords": ["error", "exception"],
    },
    {
        "task": "整理 ADAPTER 层的接口文档",
        "keywords": ["documentation"],
    },
]


def main():
    print("=" * 60)
    print("Phase 6 · 034  调度即查询（Intent Router）演示")
    print("=" * 60)

    router = IntentRouter()

    fed = FederatedGraph(DOMAIN_CONFIGS)
    counts = fed.load()
    total_nodes = sum(counts.values())
    print(f"\n已加载 {len(counts)} 个域，共 {total_nodes} 条记忆")
    for domain, n in counts.items():
        print(f"  {domain}: {n} 条")

    # ── ① 意图分类 + 路由决策 ────────────────────────────────────
    print("\n" + "─" * 50)
    print("① 意图分类 + 路由决策")
    print("─" * 50)
    for item in DEMO_TASKS:
        print()
        print(router.explain(item["task"], item["keywords"]))

    # ── ② 路由接入联邦图检索 ────────────────────────────────────
    print("\n" + "─" * 50)
    print("② 路由接入联邦图 · 实际检索结果")
    print("─" * 50)

    for item in DEMO_TASKS:
        task = item["task"]
        kws  = item["keywords"]
        cfg  = router.route(task, kws)

        print(f"\n任务: {task[:60]}")
        print(f"  路由: {cfg}")

        results = []
        for domain in cfg.domains:
            g = fed.get_graph(domain)
            if g is None:
                continue
            all_kws = kws + cfg.concept_hints
            for node in g.all_nodes():
                if node.status != "active":
                    continue
                if node.tier not in cfg.tiers:
                    continue
                node_text = " ".join(
                    [node.meta.get("title", "")]
                    + node.tags
                    + (node.meta.get("about_concepts", []) or [])
                ).lower()
                if any(k.lower() in node_text for k in all_kws):
                    results.append((domain, node))

        if results:
            for dom, node in results[:5]:
                print(f"    [{dom}] {node.id:20s} tier={node.tier:8s}  {node.meta.get('title','')[:40]}")
        else:
            print("    （无匹配节点）")

    # ── ③ 无路由 vs 有路由对比 ───────────────────────────────────
    print("\n" + "─" * 50)
    print("③ 对比：无路由（全量） vs 有路由（tier+domain 过滤）")
    print("─" * 50)

    sample = DEMO_TASKS[0]
    task  = sample["task"]
    kws   = sample["keywords"]
    cfg   = router.route(task, kws)

    # 全量 active 节点（所有域）
    all_active = [
        node
        for domain_cfg in DOMAIN_CONFIGS
        for node in (fed.get_graph(domain_cfg.name) or []).all_nodes()
        if node.status == "active"
    ]

    # 路由后候选节点
    routed_active = [
        node
        for domain in cfg.domains
        for node in (fed.get_graph(domain) or []).all_nodes()
        if node.status == "active" and node.tier in cfg.tiers
    ]

    print(f"\n  任务: {task[:60]}")
    print(f"  全量 active 节点: {len(all_active)} 条")
    print(f"  路由后候选节点:   {len(routed_active)} 条  "
          f"（域={cfg.domains}，tier={cfg.tiers}）")
    reduction = (1 - len(routed_active) / max(len(all_active), 1)) * 100
    print(f"  噪声削减:         {reduction:.0f}%")

    base_budget   = 2000
    routed_budget = int(base_budget * cfg.budget_multiplier)
    print(f"  基准 budget:      {base_budget} tokens")
    print(f"  路由后 budget:    {routed_budget} tokens  (×{cfg.budget_multiplier})")

    print("\n" + "=" * 60)
    print("Intent Router 演示完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
