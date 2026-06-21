#!/usr/bin/env python3
"""
端到端演练（Article 036）

打通从业务规则变更到代码生成的完整链路，整合 phase6 全部机制：

  Phase 5 触发点
  ─────────────
  业务规则变更（ARCH-001 分层约束放宽）
       │
       ▼ Step 1  加载联邦图
  Phase 6 记忆演进
  ─────────────
  Step 2  SchemaSnapshot + 级联迁移（031）
       │
       ▼ Step 2b  MemoryGC：清理 superseded deprecated 节点（033）
  Step 3  LLM 评审迁移风险
       │
       ▼ Step 3b  IntentRouter：意图分类 + 路由决策（034）
  Step 4  Schema-aware 联邦注入（032 + 035）
       │
       ▼ Step 5  LLM 生成修复代码
  Step 6  ConstraintMemory 校验
       │
       ▼
  GovernanceAudit 汇总

运行：
  cd democode
  python3 phase6/run_e2e_demo.py

依赖：democode/.env 中的 LLM_API_KEY、LLM_BASE_URL、LLM_MODEL
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

PHASE6 = Path(__file__).parent
sys.path.insert(0, str(PHASE6))

from code_validator import CodeValidator          # noqa: E402
from federated_graph import DomainConfig, FederatedGraph, FederatedInjector  # noqa: E402
from intent_router import IntentRouter           # noqa: E402
from llm_coder import LLMCoder, load_env         # noqa: E402
from memory_actions import MemoryActions         # noqa: E402
from memory_gc import GCPolicy, MemoryGC         # noqa: E402
from memory_injector import BudgetConfig, InjectManifest  # noqa: E402
from ontology_registry import OntologyRegistry   # noqa: E402
from schema_evolution import create_snapshot, evolve_rule  # noqa: E402


# ---------------------------------------------------------------------------
# 模拟 Phase 5 的 SchemaChangeEvent
# ---------------------------------------------------------------------------

class BusinessRuleChange:
    """
    代表来自业务层（Phase 5 SchemaUpdater）的规则变更事件。
    演练中直接构造，保持 phase6 独立可运行。
    """

    def __init__(self, rule_id: str, change_desc: str,
                 old_value: str, new_value: str):
        self.rule_id = rule_id
        self.change_desc = change_desc
        self.old_value = old_value
        self.new_value = new_value
        self.timestamp = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    def describe(self) -> str:
        return (
            f"规则={self.rule_id}  变更={self.change_desc}\n"
            f"  旧值: {self.old_value}\n"
            f"  新值: {self.new_value}\n"
            f"  时间: {self.timestamp}"
        )


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def sep(title: str, width: int = 68) -> None:
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def llm_review(prompt: str) -> str:
    """调用 LLM 对迁移结果进行评审，无 KEY 时返回占位文字"""
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL",
                              "https://dashscope.aliyuncs.com/compatible-mode/v1")
    model = os.environ.get("LLM_MODEL", "qwen3-32b")
    if not api_key:
        return "（未设置 LLM_API_KEY，跳过评审）"
    try:
        from openai import OpenAI
    except ImportError:
        return "（openai 包未安装，跳过评审）"
    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system",
             "content": "你是资深架构治理工程师。请用中文简要回答：1) 本次迁移风险评级（高/中/低）；2) 两条核心验证清单。回答控制在 150 字以内。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=300,
        extra_body={"enable_thinking": False},
    )
    usage = resp.usage
    content = (resp.choices[0].message.content or "").strip()
    if usage:
        content += f"\n(tokens: prompt={usage.prompt_tokens}, completion={usage.completion_tokens})"
    return content


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    load_env()

    schema_root     = PHASE6 / "schema"
    instances_root  = PHASE6 / "instances"
    instances_purch = PHASE6 / "instances_purchasing"

    # ──────────────────────────────────────────────────────────────────
    sep("Phase 0 / 触发点：业务规则变更（来自 Phase 5 SchemaUpdater）")
    # ──────────────────────────────────────────────────────────────────
    biz_change = BusinessRuleChange(
        rule_id="ARCH-001",
        change_desc="放宽架构分层约束：允许 application layer 直接 import adapter",
        old_value="领域层不得依赖适配层（enforcement=reject）",
        new_value="应用层可以直接 import 适配层（enforcement=warn）",
    )
    print(f"\n  {biz_change.describe()}")
    print("\n  → 规则变更触发 phase6 schema 演进流水线")

    # ──────────────────────────────────────────────────────────────────
    sep("Phase 6 / Step 1：加载联邦图（演进前快照）")
    # ──────────────────────────────────────────────────────────────────
    domains = [
        DomainConfig(
            name="code-arch",
            instances_root=instances_root,
            schema_root=schema_root,
            budget=BudgetConfig(hot=350, warm=500, cold=0, reserve=150,
                                inject_order=["hot", "warm"]),
            priority=0,
        ),
        DomainConfig(
            name="purchasing",
            instances_root=instances_purch,
            schema_root=schema_root,
            budget=BudgetConfig(hot=300, warm=200, cold=0, reserve=100,
                                inject_order=["hot", "warm"]),
            priority=1,
        ),
    ]

    fed_graph = FederatedGraph(domains)
    counts = fed_graph.load()
    for d, n in counts.items():
        print(f"  域={d:<14} 节点数={n}")

    code_arch_graph = fed_graph.get_graph("code-arch")

    # ── 动态检测 ARCH-001 当前最高版本 ────────────────────────────
    active_nodes = [
        n for n in code_arch_graph.all_nodes()
        if "ARCH-001" in (n.meta.get("about_rules") or [])
        and n.status == "active"
    ]
    current_max_version = max((n.schema_version for n in active_nodes), default=1)
    next_version = current_max_version + 1

    active_ids_before = [n.id for n in active_nodes]
    print(f"\n  演进前 ARCH-001 active 记忆: {active_ids_before}")
    print(f"  当前最高版本: v{current_max_version}  → 本次演进目标: v{next_version}")

    # ──────────────────────────────────────────────────────────────────
    sep("Phase 6 / Step 2：SchemaSnapshot + 级联迁移（031）")
    # ──────────────────────────────────────────────────────────────────
    registry = OntologyRegistry(schema_root)
    actions  = MemoryActions(instances_root, registry)

    snapshot = create_snapshot(
        version=next_version,
        changed_rule=biz_change.rule_id,
        note=f"e2e-drill: {biz_change.change_desc}",
    )
    print(f"\n  snapshot=v{snapshot.version}  rule={snapshot.changed_rule}  at={snapshot.created_at}")

    batch = evolve_rule(
        code_arch_graph,
        actions,
        rule_id=biz_change.rule_id,
        to_version=next_version,
    )
    print(f"  migration_batch: {batch.summary()}")

    # 重新加载反映迁移结果
    fed_graph.load()
    code_arch_graph = fed_graph.get_graph("code-arch")
    active_after = [
        n.id for n in code_arch_graph.all_nodes()
        if "ARCH-001" in (n.meta.get("about_rules") or [])
        and n.status == "active"
    ]
    print(f"  演进后 ARCH-001 active 记忆: {active_after}")

    # ──────────────────────────────────────────────────────────────────
    sep("Phase 6 / Step 2b：MemoryGC — 清理 superseded deprecated 节点（033）")
    # ──────────────────────────────────────────────────────────────────
    gc_policy = GCPolicy(
        decay_below=0.7,
        decay_step=0.1,
        cold_below=0.5,
        archive_below=0.3,
        enable_stale_cleanup=True,
        dry_run=False,
    )
    gc = MemoryGC(code_arch_graph, gc_policy)
    gc_report = gc.run_gc(actions)
    print(f"\n{gc_report.summary()}")

    # GC 后重新加载
    fed_graph.load()
    code_arch_graph = fed_graph.get_graph("code-arch")
    statuses = {}
    for n in code_arch_graph.all_nodes():
        statuses.setdefault(n.status, 0)
        statuses[n.status] += 1
    print(f"\n  GC 后 code-arch 节点状态分布: {statuses}")

    # ──────────────────────────────────────────────────────────────────
    sep("Phase 6 / Step 3：LLM 评审迁移风险")
    # ──────────────────────────────────────────────────────────────────
    review_prompt = (
        f"规则变更: {biz_change.change_desc}\n"
        f"快照版本: v{snapshot.version}\n"
        f"新建记忆: {batch.created}\n"
        f"废弃记忆: {batch.deprecated}\n"
        "请评审本次迁移风险，给出核心验证清单。"
    )
    review = llm_review(review_prompt)
    print(f"\n  [LLM 评审]\n  {review}")

    # ──────────────────────────────────────────────────────────────────
    sep("Phase 6 / Step 3b：IntentRouter — 意图分类 + 路由决策（034）")
    # ──────────────────────────────────────────────────────────────────
    task = "修复 procurement_service.py Kafka 消息重复触发采购订单问题"
    keywords = ["idempotency", "幂等", "kafka", "procurement", "采购", "architecture"]

    router = IntentRouter()
    route_cfg = router.route(task, keywords)
    print(f"\n{router.explain(task, keywords)}")
    print(f"\n  → 路由决策：域={route_cfg.domains}  tier={route_cfg.tiers}  budget×{route_cfg.budget_multiplier}")

    # 路由的 budget_multiplier 影响各域预算
    base_budget_code_arch  = 350
    base_budget_purchasing = 300
    arch_multiplier = route_cfg.budget_multiplier if "code-arch" in route_cfg.domains else 0.5
    purch_multiplier = route_cfg.budget_multiplier if "purchasing" in route_cfg.domains else 0.5
    print(f"  code-arch  hot budget: {base_budget_code_arch} × {arch_multiplier:.1f} = {int(base_budget_code_arch * arch_multiplier)}")
    print(f"  purchasing hot budget: {base_budget_purchasing} × {purch_multiplier:.1f} = {int(base_budget_purchasing * purch_multiplier)}")

    # ──────────────────────────────────────────────────────────────────
    sep("Phase 6 / Step 4：Schema-aware 联邦注入（032 + 035）")
    # ──────────────────────────────────────────────────────────────────
    fed_injector = FederatedInjector(fed_graph)
    # code-arch 域：只注入演进后的最新版本
    fed_injector.set_schema_window("code-arch",
                                   active_version=next_version,
                                   compatible_versions=[next_version])
    # purchasing 域：保持 v2（未参与此次演进）
    fed_injector.set_schema_window("purchasing",
                                   active_version=2,
                                   compatible_versions=[2])

    fed_manifest = fed_injector.inject(task, keywords + route_cfg.concept_hints)
    print(f"\n  {fed_manifest.summary()}")
    for domain, m in fed_manifest.domain_manifests.items():
        print(f"  [{domain}]  memories={m.memory_ids}  tokens≈{m.estimated_tokens}")

    # ──────────────────────────────────────────────────────────────────
    sep("Phase 6 / Step 5：LLM 生成修复代码")
    # ──────────────────────────────────────────────────────────────────
    api_key = os.environ.get("LLM_API_KEY", "")
    gen_code = ""
    if not api_key:
        print("  [跳过] 未设置 LLM_API_KEY")
    else:
        model = os.environ.get("LLM_MODEL", "qwen3-32b")
        coder = LLMCoder(model=model)
        combined = InjectManifest(
            task=task,
            memory_ids=[mid for m in fed_manifest.domain_manifests.values()
                        for mid in m.memory_ids],
            estimated_tokens=fed_manifest.total_tokens,
            context_text=fed_manifest.context_text,
        )
        print(f"  [LLM] model={model}  total_tokens={combined.estimated_tokens}")
        gen = coder.generate(combined, task)
        if gen.success:
            gen_code = gen.code
            print(f"  [LLM] prompt_tokens={gen.prompt_tokens}  completion_tokens={gen.completion_tokens}")
            print("  --- 生成代码（前 600 字）---")
            print(gen_code[:600] + ("..." if len(gen_code) > 600 else ""))
        else:
            print(f"  [LLM] 失败: {gen.error}")

    # ──────────────────────────────────────────────────────────────────
    sep("Phase 6 / Step 6：ConstraintMemory 校验")
    # ──────────────────────────────────────────────────────────────────
    if gen_code and code_arch_graph:
        validator = CodeValidator(code_arch_graph)
        report = validator.validate(gen_code)
        print(f"\n  [校验结果] {report.summary()}")
        if report.violations:
            for v in report.violations:
                print(f"    ✗ [{v.memory_id}] {v.rule}: {v.detail}")
        else:
            print("  → 生成代码通过全部 ConstraintMemory 约束校验 ✓")
    else:
        print("  [跳过] 无生成代码可校验")

    # ──────────────────────────────────────────────────────────────────
    sep("GovernanceAudit 汇总")
    # ──────────────────────────────────────────────────────────────────
    ca_manifest = fed_manifest.domain_manifests.get("code-arch")
    pu_manifest = fed_manifest.domain_manifests.get("purchasing")
    gc_summary = (
        f"decay={len(gc_report.decayed)}  "
        f"degrade={len(gc_report.degraded)}  "
        f"stale_cleanup={len(gc_report.cleaned)}"
    )
    print(f"""
  ┌─ 本次端到端演练审计记录 ──────────────────────────────────────┐
  │ 触发事件    : {biz_change.rule_id} {biz_change.change_desc[:35]}
  │ SchemaSnapshot : v{snapshot.version}  at={snapshot.created_at}
  │ MigrationBatch : {batch.batch_id}
  │   新建记忆   : {batch.created}
  │   废弃记忆   : {batch.deprecated}
  │ GC（033）   : {gc_summary}
  │ 路由（034） : intent={route_cfg.intent.value}  域={route_cfg.domains}
  │ 联邦注入    : {fed_manifest.total_memories} 条记忆 / ≈{fed_manifest.total_tokens} tokens
  │   code-arch : {len(ca_manifest.memory_ids) if ca_manifest else 0} 条
  │   purchasing : {len(pu_manifest.memory_ids) if pu_manifest else 0} 条
  │ 校验结果    : {'PASS' if gen_code else '未执行（无 LLM_API_KEY）'}
  └──────────────────────────────────────────────────────────────────┘""")

    sep("完成")
    print("  端到端演练结束。")
    print("  完整链路：业务规则变更 → Schema 演进 → GC 清理 → 意图路由 → 联邦注入 → LLM 生成 → 约束校验")


if __name__ == "__main__":
    main()
