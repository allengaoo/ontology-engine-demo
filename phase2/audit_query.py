"""
AuditQuery - 决策血统审计查询工具（第11篇配套）

OAG Layer 3 - Decision Lineage 的查询接口：
1. 按供应商查询决策模式（供应商被 AI 频繁选中，为什么？）
2. 按规则查询拦截统计（某条业务规则上线后效果如何？）
3. 按 Agent 查询决策质量（这个 Agent 有多可靠？）
4. 还原完整任务决策链（这个任务，AI 经历了什么才做出最终决策？）
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SupplierDecisionSummary:
    supplier_pk: str
    total_decisions: int
    success_count: int
    rejected_count: int
    total_amount: float
    common_rules_passed: List[str]
    common_violations: List[str]


class AuditQuery:
    def __init__(self, log_dir: Path):
        self.log_file = Path(log_dir) / "decisions.jsonl"

    def _load_events(self) -> List[Dict[str, Any]]:
        if not self.log_file.exists():
            return []

        events = []
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events

    def query_by_supplier(self, supplier_pk: str) -> SupplierDecisionSummary:
        """场景1：某供应商被 AI 频繁选中，为什么？"""
        events = [
            e for e in self._load_events()
            if e.get("params", {}).get("supplier_pk") == supplier_pk
        ]

        success = [e for e in events if e.get("outcome") == "success"]
        rejected = [e for e in events if e.get("outcome") == "rejected"]

        passed_rules = Counter()
        for e in success:
            for rule in e.get("passed_rules", []):
                passed_rules[rule] += 1

        violations = Counter()
        for e in rejected:
            if e.get("triggered_rule"):
                violations[e["triggered_rule"]] += 1

        total_amount = sum(
            float(e.get("params", {}).get("amount", 0) or 0)
            for e in success
        )

        return SupplierDecisionSummary(
            supplier_pk=supplier_pk,
            total_decisions=len(events),
            success_count=len(success),
            rejected_count=len(rejected),
            total_amount=total_amount,
            common_rules_passed=[r for r, _ in passed_rules.most_common(3)],
            common_violations=[r for r, _ in violations.most_common(3)],
        )

    def query_rule_effectiveness(self, rule_id: str) -> Dict[str, Any]:
        """场景2：某条规则上线后拦截了多少次？"""
        events = self._load_events()
        triggered = [
            e for e in events
            if e.get("outcome") == "rejected" and e.get("triggered_rule") == rule_id
        ]

        callers = Counter(e.get("caller", "unknown") for e in triggered)
        actions = Counter(e.get("action_id", "unknown") for e in triggered)

        return {
            "rule_id": rule_id,
            "rejection_count": len(triggered),
            "top_callers": dict(callers.most_common(5)),
            "top_actions": dict(actions.most_common(5)),
            "sample_rejection": triggered[-1] if triggered else None,
        }

    def query_agent_quality(self, caller: str) -> Dict[str, Any]:
        """场景3：某个 Agent 的决策质量如何？"""
        events = [e for e in self._load_events() if e.get("caller") == caller]
        success = [e for e in events if e.get("outcome") == "success"]
        rejected = [e for e in events if e.get("outcome") == "rejected"]

        violation_counter = Counter()
        for e in rejected:
            if e.get("triggered_rule"):
                violation_counter[e["triggered_rule"]] += 1

        amounts = [
            float(e.get("params", {}).get("amount", 0) or 0)
            for e in success
        ]

        return {
            "caller": caller,
            "total_decisions": len(events),
            "success_rate": round(len(success) / len(events), 2) if events else 0.0,
            "success_count": len(success),
            "rejected_count": len(rejected),
            "avg_success_amount": round(sum(amounts) / len(amounts), 2) if amounts else 0.0,
            "top_violations": dict(violation_counter.most_common(5)),
        }

    def explain_decision(self, event_id: str) -> Optional[Dict[str, Any]]:
        """按 event_id 还原单次决策上下文"""
        for e in self._load_events():
            if e.get("event_id") == event_id:
                return e
        return None

    def query_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Layer 3 - Decision Lineage 核心查询：还原一个任务的完整决策链

        回答：这个任务，Agent 经历了几轮？每轮为什么被拦截？怎么调整的？
        """
        task_log_file = self.log_file.parent / "task_decisions.jsonl"
        if not task_log_file.exists():
            return None
        with open(task_log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("task_id") == task_id:
                        return data
                except json.JSONDecodeError:
                    continue
        return None

    def list_tasks(self) -> List[Dict[str, Any]]:
        """列出所有任务的摘要（task_id、task、最终结果、轮数）"""
        task_log_file = self.log_file.parent / "task_decisions.jsonl"
        if not task_log_file.exists():
            return []
        tasks = []
        with open(task_log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    tasks.append({
                        "task_id": data.get("task_id"),
                        "task": data.get("task"),
                        "agent_mode": data.get("agent_mode"),
                        "final_outcome": data.get("final_outcome"),
                        "total_rounds": data.get("total_rounds"),
                        "executed_at": data.get("executed_at"),
                    })
                except json.JSONDecodeError:
                    continue
        return tasks

    def explain_task(self, task_id: str) -> None:
        """
        打印一个任务的完整决策链——OAG 可追溯性的直观展示

        展示："AI 看到了什么约束 → 为什么被拒绝 → 如何调整 → 最终结果"
        """
        task = self.query_task(task_id)
        if not task:
            print(f"未找到任务: {task_id}")
            return

        print(f"\n{'='*60}")
        print(f"  任务决策链还原")
        print(f"{'='*60}")
        print(f"  任务 ID  : {task['task_id']}")
        print(f"  任务描述 : {task['task']}")
        print(f"  Agent 模式: {task['agent_mode']}")
        print(f"  最终结果 : {task['final_outcome']}")
        print(f"  总轮数   : {task['total_rounds']}")
        print(f"  执行时间 : {task['executed_at']}")
        print()

        for rnd in task.get("rounds", []):
            status_icon = "✅" if rnd["engine_status"] == "success" else "❌"
            print(f"  第 {rnd['round']} 轮 [{rnd['agent_source']}] {status_icon}")
            print(f"    操作  : {rnd['action_id']}({json.dumps(rnd['params'], ensure_ascii=False)})")
            print(f"    理由  : {rnd['reasoning']}")
            print(f"    引擎  : {rnd['engine_message']}")
            if rnd.get("triggered_rule"):
                print(f"    触发规则 : {rnd['triggered_rule']}")
            if rnd.get("suggestion"):
                print(f"    本体建议 : {rnd['suggestion']}")
            print()

    def print_report(self) -> None:
        print("=" * 60)
        print("  审计查询报告")
        print("=" * 60)

        for pk in ("S-ACME-001", "S-BETA-002", "S-GAMMA-003"):
            summary = self.query_by_supplier(pk)
            if summary.total_decisions == 0:
                continue
            print(f"\n[供应商 {pk}] 决策 {summary.total_decisions} 次，"
                  f"成功 {summary.success_count}，拒绝 {summary.rejected_count}")

        for rule in ("certification_validity", "credit_limit_check"):
            stats = self.query_rule_effectiveness(rule)
            print(f"\n[规则 {rule}] 拦截 {stats['rejection_count']} 次")

        quality = self.query_agent_quality("procurement-agent-v2")
        print(f"\n[Agent {quality['caller']}] 成功率 {quality['success_rate']:.0%}，"
              f"共 {quality['total_decisions']} 次决策")

        # 展示任务决策链（Layer 3 核心）
        tasks = self.list_tasks()
        if tasks:
            print(f"\n[OAG 任务决策链] 共 {len(tasks)} 条任务记录")
            latest = tasks[-1]
            self.explain_task(latest["task_id"])
