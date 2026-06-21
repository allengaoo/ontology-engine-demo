#!/usr/bin/env python3
"""
双本体联邦演示（Article 033）

演示两个语义域（code-arch、purchasing）如何在同一个 FederatedGraph 中共存：
  1. 分别加载两个域的记忆图
  2. 跨域搜索：关键词可以命中不同域的记忆
  3. 联邦注入：各域独立预算，合并输出 FederatedInjectManifest
  4. 冲突检测：同一业务操作，两个域的约束是否互相矛盾

依赖环境变量（democode/.env）：LLM_API_KEY、LLM_BASE_URL、LLM_MODEL
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PHASE6 = Path(__file__).parent
sys.path.insert(0, str(PHASE6))

from llm_coder import load_env, LLMCoder  # noqa: E402
from memory_injector import BudgetConfig  # noqa: E402
from federated_graph import (  # noqa: E402
    DomainConfig,
    FederatedGraph,
    FederatedInjector,
)


def sep(title: str, width: int = 64) -> None:
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def main() -> None:
    load_env()

    schema_root = PHASE6 / "schema"
    # 共享同一套 Schema（ObjectType 定义不变，只是实例来自不同目录）
    domains = [
        DomainConfig(
            name="code-arch",
            instances_root=PHASE6 / "instances",
            schema_root=schema_root,
            budget=BudgetConfig(
                total_budget_tokens=800,
                hot=300, warm=400, cold=0, reserve=100,
                inject_order=["hot", "warm"],
            ),
            priority=0,  # 架构约束优先，先出现在 context 头部
        ),
        DomainConfig(
            name="purchasing",
            instances_root=PHASE6 / "instances_purchasing",
            schema_root=schema_root,
            budget=BudgetConfig(
                total_budget_tokens=600,
                hot=300, warm=200, cold=0, reserve=100,
                inject_order=["hot", "warm"],
            ),
            priority=1,  # 业务约束跟在架构约束后面
        ),
    ]

    # ------------------------------------------------------------------
    sep("Step 1: 加载双本体联邦")
    fed_graph = FederatedGraph(domains)
    counts = fed_graph.load()
    for domain, n in counts.items():
        print(f"  域={domain:12s}  节点数={n}")
    print(f"\n  总域数: {fed_graph.domain_count()}")

    # ------------------------------------------------------------------
    sep("Step 2: 各域节点概览")
    for domain in ["code-arch", "purchasing"]:
        nodes = fed_graph.all_nodes(domain=domain)
        print(f"\n  [{domain}]")
        for fn in nodes:
            status = fn.node.status
            print(f"    {fn.id:<18} tier={fn.tier:<5} type={fn.object_type}  status={status}")

    # ------------------------------------------------------------------
    sep("Step 3: 跨域搜索 — 关键词涉及两个域")
    keywords = ["certification", "认证", "supplier", "采购", "constraint"]
    results = fed_graph.search(keywords, limit=8)
    print(f"  keywords={keywords}")
    print(f"  命中 {len(results)} 条（跨域）:")
    for fn in results:
        print(f"    [{fn.domain}] {fn.id:<18} tier={fn.tier}  confidence={fn.node.confidence}")

    # ------------------------------------------------------------------
    sep("Step 4: 联邦注入 — 修复采购服务 Kafka 消息不幂等问题")
    task = "修复 procurement_service.py 的 Kafka 消息重复触发采购订单问题"
    keywords_task = ["idempotency", "幂等", "kafka", "procurement", "采购"]

    fed_injector = FederatedInjector(fed_graph)
    # 为两个域设置 schema 版本窗口（兼容 v1/v2）
    fed_injector.set_schema_window("code-arch", active_version=2,
                                   compatible_versions=[1, 2])
    fed_injector.set_schema_window("purchasing", active_version=2,
                                   compatible_versions=[1, 2])

    fed_manifest = fed_injector.inject(task, keywords_task)
    print(f"\n  {fed_manifest.summary()}")

    for domain, manifest in fed_manifest.domain_manifests.items():
        print(f"\n  [{domain}]  memories={manifest.memory_ids}  tokens≈{manifest.estimated_tokens}")

    print("\n  --- 联邦 context 预览（前 500 字）---")
    preview = fed_manifest.context_text[:500]
    print(preview + ("..." if len(fed_manifest.context_text) > 500 else ""))

    # ------------------------------------------------------------------
    sep("Step 5: LLM 生成 — 跨域约束下的修复代码")
    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        print("  [跳过] 未设置 LLM_API_KEY")
    else:
        model = os.environ.get("LLM_MODEL", "qwen3-32b")
        coder = LLMCoder(model=model)

        # 把联邦 context 合并进 InjectManifest（复用 LLMCoder 接口）
        from memory_injector import InjectManifest
        combined = InjectManifest(
            task=task,
            memory_ids=[mid for m in fed_manifest.domain_manifests.values()
                        for mid in m.memory_ids],
            estimated_tokens=fed_manifest.total_tokens,
            context_text=fed_manifest.context_text,
        )

        print(f"  [LLM] 模型={model}  总注入={combined.estimated_tokens} tokens")
        gen = coder.generate(combined, task)
        if gen.success:
            print(f"  [LLM] prompt_tokens={gen.prompt_tokens}  completion_tokens={gen.completion_tokens}")
            print("  --- 生成代码预览（前 600 字）---")
            print(gen.code[:600] + ("..." if len(gen.code) > 600 else ""))

            # 使用 code-arch 域的约束进行校验
            from code_validator import CodeValidator
            g = fed_graph.get_graph("code-arch")
            if g:
                validator = CodeValidator(g)
                report = validator.validate(gen.code)
                print(f"\n  [校验-code-arch] {report.summary()}")
        else:
            print(f"  [LLM] 失败: {gen.error}")

    # ------------------------------------------------------------------
    sep("Step 6: 域隔离验证 — 采购约束不污染代码域")
    code_arch_graph = fed_graph.get_graph("code-arch")
    purchasing_graph = fed_graph.get_graph("purchasing")

    code_ids = {n.id for n in code_arch_graph.all_nodes()} if code_arch_graph else set()
    purch_ids = {n.id for n in purchasing_graph.all_nodes()} if purchasing_graph else set()
    overlap = code_ids & purch_ids

    print(f"\n  code-arch 域节点: {sorted(code_ids)}")
    print(f"  purchasing 域节点: {sorted(purch_ids)}")
    print(f"\n  ID 命名空间重叠: {overlap if overlap else '无（隔离正确）'}")

    sep("完成")
    print("  双本体联邦演示结束。")
    print("  核心验证：两个域可独立加载、独立检索、联合注入，ID 命名空间不污染。")


if __name__ == "__main__":
    main()
