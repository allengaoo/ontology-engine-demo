#!/usr/bin/env python3
"""
第二阶段演示脚本

演示 OAG 完整链路：
1. 从 Schema 生成能力清单
2. Agent（真实 LLM 或 mock）选择操作
3. 本体引擎执行 / 拦截
4. 被拦截后根据结构化拒绝响应重试
5. 审计查询

用法:
  python3 phase2/run_phase2_demo.py
  python3 phase2/run_phase2_demo.py --manifest   # 仅打印能力清单
  python3 phase2/run_phase2_demo.py --audit      # 仅运行审计查询

环境变量（可选）:
  OPENAI_API_KEY  设置后走真实 LLM，否则自动 fallback 到 mock
  OPENAI_MODEL    默认 gpt-4o-mini
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
    print_separator("能力清单（Schema → Function Calling）")
    provider = CapabilityProvider(PHASE1_DIR / "schema")
    provider.print_manifest()


def run_agent_demo() -> None:
    print_separator("Agent 任务：向供应商发起采购")
    reset_demo_data()
    gateway = AgentGateway(PHASE1_DIR)
    task = "为生产线补充工业胶水，向合适的供应商发起采购订单"
    gateway.execute_agent_task(task)


def run_audit() -> None:
    print_separator("审计查询")
    query = AuditQuery(PHASE1_DIR / "logs")
    query.print_report()

    # 尝试解释一条成功决策（若存在）
    events = query._load_events()
    success_events = [e for e in events if e.get("outcome") == "success"]
    if success_events:
        evt = success_events[0]
        print(f"\n示例：解释决策 {evt['event_id']}")
        print(f"  操作: {evt['action_id']}")
        print(f"  调用方: {evt['caller']}")
        print(f"  通过规则: {', '.join(evt.get('passed_rules', []))}")


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
