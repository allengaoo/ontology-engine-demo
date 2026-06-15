#!/usr/bin/env python3
"""
Phase 6 演示：记忆本体内核 — 端到端编码闭环

演示步骤（Article 029）：
  1. 加载 Schema → 列出 ObjectType
  2. 加载 instances → 建图索引
  3. Schema 执法：拒绝非法写入
  4. hybrid_search + inject → InjectManifest（模型透明）
  5. 调用 qwen3-32b：InjectManifest → 生成修复代码
  6. ConstraintMemory 校验：检查生成代码是否违反硬约束
  7. schema_evolution 健康度扫描

核心命题验证：端侧小模型 + 本体记忆 = 生产级代码
"""

import sys
from pathlib import Path

PHASE6 = Path(__file__).parent
sys.path.insert(0, str(PHASE6))

from ontology_registry import OntologyRegistry
from memory_graph import MemoryGraph
from hybrid_search import HybridSearch
from memory_injector import MemoryInjector
from memory_actions import MemoryActions
from schema_evolution import analyze_graph
from llm_coder import LLMCoder, load_env
from code_validator import CodeValidator


def sep(title: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def main() -> None:
    load_env()

    schema_root = PHASE6 / "schema"
    instances_root = PHASE6 / "instances"

    sep("Step 1: 加载记忆本体 Schema")
    registry = OntologyRegistry(schema_root)
    print(f"  ObjectTypes: {registry.list_object_types()}")
    print(f"  Layers: {sorted(registry.layers)}")

    sep("Step 2: 加载记忆图 (instances/*.md)")
    graph = MemoryGraph(instances_root, registry)
    n = graph.load()
    print(f"  节点数: {n}")
    for node in graph.all_nodes():
        print(f"    - {node.id} [{node.object_type}] tier={node.tier} layer={node.layer}")

    sep("Step 3: Schema 执法 — 非法写入应被拒绝")
    actions = MemoryActions(instances_root, registry)
    bad_meta = {
        "id": "BAD-001",
        "object_type": "ConstraintMemory",
        "title": "缺少 rule_id",
        "layer": "CROSS_CUTTING",
        "tier": "hot",
        "tags": ["test"],
    }
    result = actions.write_memory(bad_meta, "## HOW\n无效\n")
    if not result.ok:
        print(f"  ✓ 预期拒绝: {result.errors}")

    sep("Step 4: 图检索 + 注入（模型透明）")
    task = "修复 kafka_producer.py 中 Avro 序列化失败的问题"
    keywords = ["avro", "serialization", "序列化", "schema-registry"]
    search = HybridSearch(graph)
    hits = search.search(keywords)
    print(f"  任务: {task}")
    print(f"  hybrid_search 命中: {[n.id for n in hits]}")

    injector = MemoryInjector(graph, schema_root)
    manifest = injector.inject(task, keywords)
    print(f"  InjectManifest: {manifest.summary()}")
    print(f"  tiers: {manifest.tiers}")
    print("  --- 注入上下文预览（前 400 字）---")
    preview = manifest.context_text[:400]
    print(preview + ("..." if len(manifest.context_text) > 400 else ""))

    sep("Step 5: 调用 qwen3-32b 生成修复代码")
    coder = LLMCoder(model="qwen3-32b")
    print(f"  模型: {coder.model}")
    print(f"  base_url: {coder.base_url}")
    print(f"  调用中...")

    gen_result = coder.generate(manifest, task)
    if not gen_result.success:
        print(f"  ✗ 生成失败: {gen_result.error}")
        print("  (跳过校验步骤)")
    else:
        print(f"  ✓ 生成成功")
        print(f"  prompt_tokens: {gen_result.prompt_tokens}")
        print(f"  completion_tokens: {gen_result.completion_tokens}")
        print(f"  --- 生成代码预览（前 800 字）---")
        code_preview = gen_result.code[:800]
        print(code_preview + ("..." if len(gen_result.code) > 800 else ""))

        sep("Step 6: ConstraintMemory 校验生成代码")
        validator = CodeValidator(graph)
        report = validator.validate(gen_result.code)
        print(f"  {report.summary()}")
        if not report.passed:
            for v in report.violations:
                print(f"    ✗ [{v.memory_id}] {v.rule}: {v.detail}")
        else:
            print("  端侧小模型 + 本体记忆注入 → 生成代码通过约束校验 ✓")

    sep("Step 7: Schema 演进健康度（骨架）")
    report = analyze_graph(graph)
    print(f"  {report.summary()}")
    for w in report.warnings:
        print(f"    ⚠ {w}")

    sep("完成")
    print("  记忆本体内核端到端演示结束。")
    print("  核心验证：InjectManifest → qwen3-32b → ConstraintMemory 校验")
    print("  完整 GC / 级联 / 意图漏斗见 Phase 6 后续文章与代码扩展。")


if __name__ == "__main__":
    main()
