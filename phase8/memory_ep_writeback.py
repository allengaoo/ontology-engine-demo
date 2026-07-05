"""
memory_ep_writeback — EP 级写回：DecisionRecord + StructurePlan 模板（Phase 8 P1）
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.structure_plan import StructurePlan
from harness.ep_promotion import PromotionItem, PromotionTarget
from memory_actions import MemoryActions


class MemoryEPWriteback:
    """按 PromotionPlan 执行 Ontology 写回。"""

    def __init__(self, actions_by_domain: Dict[str, MemoryActions]):
        self.actions_by_domain = actions_by_domain

    def apply_item(
        self,
        item: PromotionItem,
        *,
        task_description: str,
        primary_domain: str = "code-arch",
        dry_run: bool = False,
    ) -> Optional[str]:
        if item.target == PromotionTarget.SHARED_DECISION:
            return self._write_decision(item.payload, task_description, primary_domain, dry_run)
        if item.target == PromotionTarget.SHARED_PATTERN:
            return self._write_plan_pattern(item.payload, task_description, primary_domain, dry_run)
        return None

    def _write_decision(
        self,
        payload: Dict[str, Any],
        task_description: str,
        domain: str,
        dry_run: bool,
    ) -> Optional[str]:
        actions = self.actions_by_domain.get(domain)
        if actions is None:
            return None

        ep_id = payload.get("ep_id", "ep-unknown")
        now = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        node_id = f"DEC-EP-{ep_id.replace('ep-', '')[:8]}-{now[-6:]}"
        derived = payload.get("derived_from", [])

        meta = {
            "id": node_id,
            "object_type": "DecisionRecord",
            "title": f"EP 成功：{payload.get('plan_id', ep_id)}",
            "layer": "DOMAIN",
            "tier": "warm",
            "tags": ["ep-success", "kafka", "idempotency", "procurement"],
            "confidence": 0.92,
            "schema_version": 2,
            "decision": (
                f"action={payload.get('action', 'apply_idempotency_pattern')} "
                f"units={payload.get('units', [])}"
            )[:500],
            "about_concepts": ["kafka-idempotency", "procurement", "ep-writeback"],
            "derived_from": derived[:10],
            "status": "active",
            "domain": domain,
        }
        body = (
            f"## 背景\n\nEP {ep_id}：{task_description[:300]}\n\n"
            f"## 决策\n\n"
            f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## 血统\n\n"
            f"derived_from: {derived}\n"
        )

        if dry_run:
            print(f"  [ep_writeback/dry-run] DecisionRecord → {domain}/{node_id}.md")
            return node_id

        result = actions.write_memory(meta, body)
        return node_id if result.ok else None

    def _write_plan_pattern(
        self,
        payload: Dict[str, Any],
        task_description: str,
        domain: str,
        dry_run: bool,
    ) -> Optional[str]:
        actions = self.actions_by_domain.get("purchasing") or self.actions_by_domain.get(domain)
        if actions is None:
            return None

        plan_id = payload.get("plan_id", "plan-unknown")
        node_id = f"BIZ-PAT-EP-{plan_id.replace('plan-', '')[:8]}"
        derived = payload.get("derived_from", [])

        meta = {
            "id": node_id,
            "object_type": "PatternMemory",
            "title": f"StructurePlan 模板：{payload.get('action', '')}",
            "layer": "DOMAIN",
            "tier": "warm",
            "tags": ["structure-plan", "ep-template", "kafka"],
            "confidence": 0.85,
            "schema_version": 2,
            "about_concepts": ["idempotency", "procurement", "structure-plan"],
            "derived_from": derived[:10],
            "status": "active",
            "domain": "purchasing",
        }
        paths = payload.get("unit_paths", [])
        body = (
            f"## HOW\n\n"
            f"Kafka 幂等类任务可参考本 EP 的 Unit 切分：\n"
            + "\n".join(f"- {p}" for p in paths)
            + f"\n\n共 {payload.get('unit_count', 0)} 个 Unit，action={payload.get('action')}。\n\n"
            f"## WHEN\n\n"
            f"同类 procurement / kafka 幂等修复任务；EP 锚定后 inject 可检索本模板。\n\n"
            f"## 来源\n\n"
            f"task: {task_description[:200]}\n"
        )

        if dry_run:
            print(f"  [ep_writeback/dry-run] PatternMemory → purchasing/{node_id}.md")
            return node_id

        result = actions.write_memory(meta, body)
        return node_id if result.ok else None

    def apply_structure_plan(
        self,
        structure_plan: StructurePlan,
        task_description: str,
        dry_run: bool = False,
    ) -> Optional[str]:
        """便捷方法：直接写 Plan 模板。"""
        item = PromotionItem(
            target=PromotionTarget.SHARED_PATTERN,
            reason="StructurePlan template",
            payload={
                "plan_id": structure_plan.plan_id,
                "action": structure_plan.action,
                "unit_count": len(structure_plan.units),
                "unit_paths": [u.target_path for u in structure_plan.units],
                "derived_from": structure_plan.derived_from,
            },
        )
        return self.apply_item(item, task_description=task_description, dry_run=dry_run)
