#!/usr/bin/env python3
"""
Schema 演进演示：快照 -> 级联迁移 -> 注入收敛 -> LLM 评审 -> 可选回滚

依赖环境变量（从 democode/.env 自动加载）：
  - LLM_API_KEY
  - LLM_BASE_URL（可选）
  - LLM_MODEL（可选，默认 qwen3-32b）
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PHASE6 = Path(__file__).parent
sys.path.insert(0, str(PHASE6))

from llm_coder import load_env  # noqa: E402
from memory_actions import MemoryActions  # noqa: E402
from memory_graph import MemoryGraph  # noqa: E402
from memory_injector import MemoryInjector  # noqa: E402
from ontology_registry import OntologyRegistry  # noqa: E402
from schema_evolution import create_snapshot, evolve_rule, rollback_batch  # noqa: E402


def sep(title: str) -> None:
    print("\n" + "=" * 64)
    print(f"  {title}")
    print("=" * 64)


def llm_review(prompt: str) -> tuple[bool, str]:
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get(
        "LLM_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    model = os.environ.get("LLM_MODEL", "qwen3-32b")

    if not api_key:
        return False, "LLM_API_KEY 未设置，跳过大模型评审。"

    try:
        from openai import OpenAI
    except Exception:
        return False, "openai 包未安装，请先安装：pip install openai"

    client = OpenAI(api_key=api_key, base_url=base_url)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是资深架构治理工程师。请用中文输出："
                        "1) 风险评估（高/中/低）；2) 三条验证清单；3) 一条回滚触发条件。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=600,
            extra_body={"enable_thinking": False},
        )
    except Exception as exc:
        return False, f"LLM 调用失败: {exc}"

    content = (resp.choices[0].message.content or "").strip()
    usage = resp.usage
    usage_text = ""
    if usage:
        usage_text = f"\n(tokens: prompt={usage.prompt_tokens}, completion={usage.completion_tokens})"
    return True, content + usage_text


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase6 Schema 演进演示（含大模型评审）")
    parser.add_argument("--rule-id", default="ARCH-001", help="目标规则 ID")
    parser.add_argument("--to-version", type=int, default=2, help="目标 schema_version")
    parser.add_argument("--rollback", action="store_true", help="演示完成后执行回滚")
    args = parser.parse_args()

    load_env()

    schema_root = PHASE6 / "schema"
    instances_root = PHASE6 / "instances"
    registry = OntologyRegistry(schema_root)
    graph = MemoryGraph(instances_root, registry)
    actions = MemoryActions(instances_root, registry)

    sep("Step 1: 加载当前记忆图")
    graph.load()
    active_before = [n.id for n in graph.find_active_by_rule(args.rule_id)]
    print(f"rule={args.rule_id} active_before={active_before}")

    sep("Step 2: 创建 SchemaSnapshot 并执行级联迁移")
    snapshot = create_snapshot(
        version=args.to_version,
        changed_rule=args.rule_id,
        note="schema evolution demo",
    )
    print(f"snapshot=v{snapshot.version} changed_rule={snapshot.changed_rule} at={snapshot.created_at}")

    batch = evolve_rule(graph, actions, rule_id=args.rule_id, to_version=args.to_version)
    print(f"migration_batch={batch.summary()}")

    sep("Step 3: 重新加载并验证注入收敛")
    graph.load()
    injector = MemoryInjector(graph, schema_root)
    injector.set_schema_window(active_version=args.to_version, compatible_versions=[args.to_version])
    manifest = injector.inject(
        task="校验 schema 演进后的记忆注入窗口",
        keywords=["layering", "dependency-rule", "schema"],
    )
    print(f"inject_manifest={manifest.summary()}")

    sep("Step 4: 调用大模型评审迁移结果")
    prompt = (
        f"规则ID: {args.rule_id}\n"
        f"快照版本: v{snapshot.version}\n"
        f"迁移批次: {batch.batch_id}\n"
        f"新建记忆: {batch.created}\n"
        f"废弃记忆: {batch.deprecated}\n"
        f"注入窗口(memory_ids): {manifest.memory_ids}\n"
        f"注入估算tokens: {manifest.estimated_tokens}\n"
        "请评审本次迁移是否可上线，并给出验证清单。"
    )
    ok, review = llm_review(prompt)
    if ok:
        print("LLM_REVIEW:\n" + review)
    else:
        print(f"LLM_REVIEW_SKIP: {review}")

    if args.rollback:
        sep("Step 5: 执行回滚演示")
        graph.load()
        rollback_batch(graph, actions, batch)
        graph.load()
        active_after_rollback = [n.id for n in graph.find_active_by_rule(args.rule_id)]
        print(f"rollback_done batch={batch.batch_id} active_after={active_after_rollback}")

    sep("完成")
    print("Schema 演进演示结束。")


if __name__ == "__main__":
    main()
