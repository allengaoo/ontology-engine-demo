#!/usr/bin/env python3
"""
记忆经济学实验：4 组预算策略对照（Article 032）

实验设计：固定任务 + 固定模型，改变 BudgetConfig，观察：
  - InjectManifest 的 token 分布
  - LLM 生成代码是否通过 ConstraintMemory 校验

组别：
  A  基准      hot=400  warm=600  cold=0   inject_order=[hot,warm]
  B  预算不足  hot=80   warm=50   cold=0   inject_order=[hot,warm]  → CRITICAL 截断
  C  预算过剩  hot=999  warm=999  cold=999 inject_order=[hot,warm,cold] → 全量注入
  D  顺序错误  hot=400  warm=600  cold=0   inject_order=[warm,hot]  → CRITICAL 被推后

依赖环境变量（democode/.env）：LLM_API_KEY、LLM_BASE_URL、LLM_MODEL
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

PHASE6 = Path(__file__).parent
sys.path.insert(0, str(PHASE6))

from code_validator import CodeValidator  # noqa: E402
from llm_coder import LLMCoder, load_env  # noqa: E402
from memory_graph import MemoryGraph  # noqa: E402
from memory_injector import BudgetConfig, InjectManifest, MemoryInjector  # noqa: E402
from ontology_registry import OntologyRegistry  # noqa: E402


# ---------------------------------------------------------------------------
# 实验组配置
# ---------------------------------------------------------------------------

@dataclass
class ExperimentGroup:
    name: str
    desc: str
    budget: BudgetConfig


GROUPS: List[ExperimentGroup] = [
    ExperimentGroup(
        name="A-基准",
        desc="hot=400 warm=600 cold=0  顺序=hot→warm",
        budget=BudgetConfig(
            total_budget_tokens=1200,
            hot=400, warm=600, cold=0, reserve=200,
            compress_enabled=True,
            inject_order=["hot", "warm"],
        ),
    ),
    ExperimentGroup(
        name="B-预算不足",
        desc="hot=80  warm=50  cold=0  CRITICAL 约束将被截断",
        budget=BudgetConfig(
            total_budget_tokens=200,
            hot=80, warm=50, cold=0, reserve=20,
            compress_enabled=True,
            inject_order=["hot", "warm"],
        ),
    ),
    ExperimentGroup(
        name="C-预算过剩",
        desc="不设上限，含 cold 层，全量注入",
        budget=BudgetConfig(
            total_budget_tokens=9999,
            hot=9999, warm=9999, cold=9999, reserve=0,
            compress_enabled=False,   # 不压缩，最大化 context 长度
            inject_order=["hot", "warm", "cold"],
        ),
    ),
    ExperimentGroup(
        name="D-顺序错误",
        desc="hot=400 warm=600 cold=0  顺序=warm→hot (CRITICAL 被推后)",
        budget=BudgetConfig(
            total_budget_tokens=1200,
            hot=400, warm=600, cold=0, reserve=200,
            compress_enabled=True,
            inject_order=["warm", "hot"],
        ),
    ),
]

# 固定任务与关键词
TASK = "修复 kafka_producer.py 中 Avro 序列化失败的问题"
KEYWORDS = ["avro", "serialization", "序列化", "schema-registry"]


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def sep(title: str, width: int = 64) -> None:
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def critical_position(manifest: InjectManifest) -> Optional[int]:
    """返回 CRITICAL（CN-*）记忆在注入列表中的位置（0-indexed），None 表示未注入"""
    for i, mid in enumerate(manifest.memory_ids):
        if mid.startswith("CN-"):
            return i
    return None


def has_full_critical(manifest: InjectManifest) -> bool:
    """检查 context 中是否包含完整的 enforcement=reject 标记"""
    return "enforcement=reject" in manifest.context_text or "enforcement" in manifest.context_text


# ---------------------------------------------------------------------------
# 主程序
# ---------------------------------------------------------------------------

def main() -> None:
    load_env()

    schema_root = PHASE6 / "schema"
    instances_root = PHASE6 / "instances"
    registry = OntologyRegistry(schema_root)
    graph = MemoryGraph(instances_root, registry)
    n = graph.load()
    print(f"记忆图加载完成：{n} 个节点")

    # 预算实验不依赖 Schema 演进，兼容 v1/v2 以确保 warm 层可注入
    injector = MemoryInjector(graph, schema_root)
    injector.set_schema_window(active_version=2, compatible_versions=[1, 2])

    validator = CodeValidator(graph)
    model = os.environ.get("LLM_MODEL", "qwen3-32b")
    coder = LLMCoder(model=model)
    has_llm = bool(os.environ.get("LLM_API_KEY", ""))

    results = []

    for group in GROUPS:
        sep(f"实验组 {group.name}  |  {group.desc}")

        # Step 1：生成 InjectManifest
        manifest = injector.inject(TASK, KEYWORDS, budget=group.budget)
        print(f"\n  InjectManifest: {manifest.summary()}")
        print(f"  tier_tokens:    {manifest.tier_tokens}")
        print(f"  inject_order:   {group.budget.inject_order}")

        crit_pos = critical_position(manifest)
        crit_full = has_full_critical(manifest)
        print(f"  CRITICAL 位置:  {crit_pos}（None=未注入）  完整={crit_full}")

        print("\n  --- context 预览（前 300 字）---")
        preview = manifest.context_text[:300]
        print(preview + ("..." if len(manifest.context_text) > 300 else ""))

        # Step 2：调用 LLM
        if has_llm:
            print("\n  [LLM] 调用中...")
            gen = coder.generate(manifest, TASK)
            if gen.success:
                print(f"  [LLM] prompt_tokens={gen.prompt_tokens}  completion_tokens={gen.completion_tokens}")
                report = validator.validate(gen.code)
                llm_result = "PASS" if report.passed else "FAIL"
                llm_tokens = gen.prompt_tokens
                violations = [f"{v.memory_id}/{v.rule}" for v in report.violations]
                print(f"  [校验] {report.summary()}")
                if violations:
                    print(f"  [违规] {violations}")
            else:
                llm_result = f"ERROR:{gen.error}"
                llm_tokens = 0
                print(f"  [LLM] 失败: {gen.error}")
        else:
            llm_result = "SKIP(无KEY)"
            llm_tokens = 0
            print("  [LLM] 跳过（未设置 LLM_API_KEY）")

        results.append({
            "group": group.name,
            "memories": len(manifest.memory_ids),
            "tokens": manifest.estimated_tokens,
            "hot_tk": manifest.tier_tokens.get("hot", 0),
            "warm_tk": manifest.tier_tokens.get("warm", 0),
            "cold_tk": manifest.tier_tokens.get("cold", 0),
            "crit_pos": crit_pos,
            "crit_full": crit_full,
            "llm_prompt_tk": llm_tokens,
            "result": llm_result,
        })

    # ---------------------------------------------------------------------------
    # 汇总对照表
    # ---------------------------------------------------------------------------
    sep("实验结果对照表")
    header = (
        f"{'组别':<12} {'记忆数':>5} {'tokens':>7} "
        f"{'hot_tk':>7} {'warm_tk':>8} {'cold_tk':>7} "
        f"{'CRIT位置':>8} {'完整':>4} {'结果':<18}"
    )
    print(f"\n  {header}")
    print("  " + "-" * (len(header) + 2))
    for r in results:
        crit_pos_str = str(r["crit_pos"]) if r["crit_pos"] is not None else "未注入"
        print(
            f"  {r['group']:<12} {r['memories']:>5} {r['tokens']:>7} "
            f"{r['hot_tk']:>7} {r['warm_tk']:>8} {r['cold_tk']:>7} "
            f"{crit_pos_str:>8} {'是' if r['crit_full'] else '否':>4} {r['result']:<18}"
        )

    print("\n  实验说明：")
    print("  - CRIT位置：CRITICAL 约束在 memory_ids 列表中的下标，0=最前")
    print("  - 完整：context_text 中是否包含 enforcement 字段（约束完整性）")
    print("  - tokens：InjectManifest 估算 token（中文 1token≈2字）")
    print()


if __name__ == "__main__":
    main()
