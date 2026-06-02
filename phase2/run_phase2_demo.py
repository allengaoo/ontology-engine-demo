#!/usr/bin/env python3
"""
第二阶段演示脚本 —— OAG 完整链路

OAG（Ontology Augmented Generation）三层能力展示：

  Layer 1 - Capability Discovery（能力发现）
    本体 Schema → Function Calling 格式 → Agent 的"操作手册"
    同一份 YAML，对人可读，对 Agent 可执行

  Layer 2 - Execution Constraints（执行约束）
    Agent 发起操作 → 引擎实时校验业务规则 → 违规则强制回滚
    拒绝响应结构化：触发规则 + 当前状态快照 + Schema 驱动建议
    Agent 收到建议 → 重新生成决策（OAG 的 "G"）

  Layer 3 - Decision Lineage（决策血统）
    任务级日志记录完整决策链（task_decisions.jsonl）
    事后可还原："AI 看到了什么 → 为什么被拒 → 如何调整 → 最终结果"

用法:
  python3 phase2/run_phase2_demo.py              # 完整演示
  python3 phase2/run_phase2_demo.py --manifest   # 仅打印能力清单（Layer 1）
  python3 phase2/run_phase2_demo.py --audit      # 仅运行审计查询（Layer 3）

环境变量（democode/.env）:
  LLM_API_KEY   设置后走真实 LLM，否则自动 fallback 到 mock
  LLM_BASE_URL  自定义 API 地址（兼容 OpenAI / DeepSeek 等）
  LLM_MODEL     模型名称（默认 gpt-4o-mini）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PHASE1_DIR = ROOT / "phase1"
sys.path.insert(0, str(ROOT))

from phase2.capability_provider import CapabilityProvider
from phase2.agent_gateway import AgentGateway
from phase2.audit_query import AuditQuery
from phase2.demo_data import INITIAL_SUPPLIERS, INITIAL_CERTIFICATIONS


def reset_demo_data() -> None:
    """重置演示数据，保证 phase2 可独立复现"""
    data_dir = PHASE1_DIR / "data"
    with open(data_dir / "Supplier.json", "w", encoding="utf-8") as f:
        json.dump(INITIAL_SUPPLIERS, f, ensure_ascii=False, indent=2)
    with open(data_dir / "Certification.json", "w", encoding="utf-8") as f:
        json.dump(INITIAL_CERTIFICATIONS, f, ensure_ascii=False, indent=2)
    with open(data_dir / "PurchaseOrder.json", "w", encoding="utf-8") as f:
        json.dump([], f)
    log_file = PHASE1_DIR / "logs" / "decisions.jsonl"
    if log_file.exists():
        log_file.unlink()


def print_separator(title: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60 + "\n")


def run_manifest() -> None:
    print_separator("Layer 1 - Capability Discovery：Schema → Agent 操作手册")
    provider = CapabilityProvider(PHASE1_DIR / "schema")
    provider.print_manifest()


def run_agent_demo() -> None:
    print_separator("Layer 2 - Execution Constraints + OAG Generation：Agent 任务执行")
    reset_demo_data()
    gateway = AgentGateway(PHASE1_DIR)
    task = (
        "为生产线补充工业胶水，向合适的供应商发起采购订单。"
        "当前可用供应商：S-ACME-001（ACME，认证有效）、S-BETA-002（Beta，认证即将过期）、"
        "S-GAMMA-003（Gamma，信用额度已接近上限）。"
        "请选择合规的供应商，采购金额约 80000 元，数量 500 件。"
    )
    gateway.execute_agent_task(task)


def run_audit() -> None:
    print_separator("Layer 3 - Decision Lineage：审计查询与决策链还原")
    query = AuditQuery(PHASE1_DIR / "logs")
    query.print_report()


def main() -> None:
    parser = argparse.ArgumentParser(description="第二阶段 OAG 演示")
    parser.add_argument("--manifest", action="store_true", help="仅打印能力清单")
    parser.add_argument("--audit", action="store_true", help="仅运行审计查询")
    args = parser.parse_args()

    if args.manifest:
        run_manifest()
        return

    if args.audit:
        run_audit()
        return

    run_manifest()
    run_agent_demo()
    run_audit()


if __name__ == "__main__":
    main()
