"""
memory_ep_writeback — EP 级写回：DecisionRecord + StructurePlan 模板（Phase 8 P1）
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

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
        if item.target == PromotionTarget.SHARED_ANTI:
            return self._write_anti(item.payload, task_description, primary_domain, dry_run)
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
            "tags": ["ep-success", "oncall", "shared-memory", "ep-writeback"],
            "confidence": 0.92,
            "schema_version": 2,
            "decision": (
                f"action={payload.get('action', 'implement_oncall')} "
                f"units={payload.get('units', [])}"
            )[:500],
            "about_concepts": ["oncall", "roster", "ep-writeback"],
            "derived_from": derived[:10],
            "status": "active",
            "domain": domain,
            "memory_kind": "shared",
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
        actions = self.actions_by_domain.get("domain") or self.actions_by_domain.get(domain)
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
            "tags": ["structure-plan", "ep-template", "oncall"],
            "confidence": 0.85,
            "schema_version": 2,
            "about_concepts": ["oncall", "structure-plan", "roster"],
            "derived_from": derived[:10],
            "status": "active",
            "domain": "domain",
        }
        paths = payload.get("unit_paths", [])
        body = (
            f"## HOW\n\n"
            f"同类 oncall 任务可参考本 EP 的 Unit 切分：\n"
            + "\n".join(f"- {p}" for p in paths)
            + f"\n\n共 {payload.get('unit_count', 0)} 个 Unit，action={payload.get('action')}。\n\n"
            f"## WHEN\n\n"
            f"同类排班 / 冲突检测任务；EP 锚定后 inject 可检索本模板。\n\n"
            f"## 来源\n\n"
            f"task: {task_description[:200]}\n"
        )

        if dry_run:
            print(f"  [ep_writeback/dry-run] PatternMemory → domain/{node_id}.md")
            return node_id

        result = actions.write_memory(meta, body)
        return node_id if result.ok else None

    @staticmethod
    def _anti_digest(
        rule_id: str,
        detail: str,
        violations: Sequence[Any],
        cmd: str,
        task_description: str,
    ) -> Dict[str, str]:
        """从失败反馈提炼可执行避坑条款。"""
        import re

        key_lines: List[str] = []
        for v in violations or []:
            s = str(v).strip()
            if s:
                key_lines.append(s)
        for line in (cmd or "").splitlines():
            if any(
                k in line
                for k in (
                    "FAILED",
                    "ERROR",
                    "E   ",
                    "TypeError",
                    "ImportError",
                    "AttributeError",
                    "AssertionError",
                    "FastAPIError",
                    "freeze",
                    "SCHEMA",
                    "VITE",
                )
            ):
                key_lines.append(line.strip())
        # 去重保序
        seen = set()
        uniq: List[str] = []
        for x in key_lines:
            if x not in seen:
                seen.add(x)
                uniq.append(x)
        tip = uniq[0][:160] if uniq else (detail or rule_id)[:160]
        blob = "\n".join(uniq + [task_description, detail, cmd])
        meeting = "meeting_order" in blob or "meeting_order" in tip
        files = re.findall(
            r"(backend/src/(?:meeting_order|oncall)/[^\s:]+|tests/(?:meeting_order|oncall)/[^\s:]+|frontend/src/[^\s:]+)",
            blob,
        )
        file_hint = (
            ", ".join(list(dict.fromkeys(files))[:4]) if files else "（未解析到文件）"
        )
        if meeting:
            fix = (
                "只改 meeting_order 包；import 只用 from meeting_order...；"
                "对齐 repositories.base.MeetingRepository + factory.get_repository/init_db；"
                "禁止 oncall / invent repositories.booking"
            )
        else:
            fix = "读上游签名后只改未 freeze 文件；Roster 用 shifts；对齐 oncall_schema.json"
        if "No module named 'oncall'" in blob or "from oncall" in blob:
            fix = (
                "禁止任何 oncall 导入；改为 meeting_order.config / "
                "meeting_order.repositories.factory；先扫全包 import 再改"
            )
        elif "IMPORT-CROSS-APP" in rule_id or "IMPORT-CROSS-APP" in blob:
            fix = "生成代码不得出现 import/from oncall；包名必须与目标路径一致"
        elif "BaseRepository" in blob or "BaseBookingRepository" in blob:
            fix = "使用 MeetingRepository（repositories/base.py）；禁止 BaseRepository 旧名"
        elif "repositories.booking" in blob or "repositories.room" in blob:
            fix = "禁止 invent repositories.booking/room；只用 base + factory + sqlite_repo"
        elif "freeze" in tip.lower() or "freeze" in detail.lower():
            fix = "不要改 models/；只实现下游并对齐已有 dataclass 字段"
        elif "VITE" in rule_id or "@/" in tip:
            fix = "去掉 @/，改用相对 import；保证 vite build"
        elif "response_model" in tip or "Pydantic" in tip or "FastAPIError" in tip:
            fix = "修正 FastAPI 返回类型/response_model；请求体用 CreateBookingRequest"
        elif "engineers" in tip and "Roster" in tip:
            fix = "禁止 Roster(engineers=)；使用 Roster(shifts=...)"
        elif "JSONDecodeError" in blob or "seed_rooms" in blob:
            fix = "data/seed_rooms.json 必须是合法 JSON 数组；用 config.ROOT / data/seed_rooms.json"
        elif "takes 1 positional argument but 2" in blob and "SqliteRepository" in blob:
            fix = "SqliteRepository() 无参；factory 不要传 DB_PATH 给构造器"
        title = f"{rule_id}: {tip}"[:80]
        return {
            "title": title,
            "tip": tip,
            "file_hint": file_hint,
            "fix_path": fix,
            "signals": "\n".join(f"- {x}" for x in uniq[:12]) or f"- {detail}",
            "app": "meeting_order" if meeting else "oncall",
        }

    def _write_anti(
        self,
        payload: Dict[str, Any],
        task_description: str,
        domain: str,
        dry_run: bool,
    ) -> Optional[str]:
        """FAIL → AntiPatternMemory，tier=hot，带 gc_protect 免快速衰减。"""
        actions = self.actions_by_domain.get("domain") or self.actions_by_domain.get(domain)
        if actions is None:
            return None

        ep_id = payload.get("ep_id", "ep-unknown")
        now = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        node_id = f"ANTI-EP-{ep_id.replace('ep-', '')[:8]}-{now[-6:]}"
        rule_id = payload.get("rule_id") or "FAIL"
        detail = (payload.get("detail") or "")[:300]
        violations = payload.get("violations") or []
        cmd = (payload.get("command_output") or "")[:2000]
        digest = self._anti_digest(rule_id, detail, violations, cmd, task_description)
        app = digest.get("app") or "oncall"
        concepts = (
            ["meeting_order", "booking", "ep-fail"]
            if app == "meeting_order"
            else ["oncall", "roster", "ep-fail"]
        )

        meta = {
            "id": node_id,
            "object_type": "AntiPatternMemory",
            "title": digest["title"],
            "layer": "DOMAIN",
            "tier": "hot",
            "tags": [
                "ep-fail",
                "anti",
                app,
                "gc-protect",
                "shared-memory",
                "ep-writeback",
            ],
            "confidence": 0.95,
            "schema_version": 2,
            "about_concepts": concepts,
            "status": "active",
            "domain": "domain",
            "memory_kind": "shared",
            "severity": "high",
            "detection_signals": [rule_id, digest["tip"], digest["file_hint"]][:8],
            "fix_path": digest["fix_path"],
            "gc_protect": True,
            "gc_note": "FAIL→ANTI hot；age_idle_decay 跳过 gc-protect",
        }
        when = (
            "同类 meeting_order 预订任务；下一轮 Repair 必须先避开本条再改代码。"
            if app == "meeting_order"
            else "同类 oncall 任务；Repair EP 必须先说明如何避开再改代码。"
        )
        body = (
            f"## HOW\n\n"
            f"可执行避坑：\n"
            f"- rule_id: `{rule_id}`\n"
            f"- 关键错误: {digest['tip']}\n"
            f"- 涉及文件: {digest['file_hint']}\n"
            f"- 修复路径: {digest['fix_path']}\n"
            f"- task: {task_description[:240]}\n\n"
            f"## 信号\n\n"
            f"{digest['signals']}\n\n"
            f"## pytest/编译摘录\n\n"
            f"```\n{cmd[:1500]}\n```\n\n"
            f"## WHEN\n\n"
            f"{when}\n"
        )

        if dry_run:
            print(f"  [ep_writeback/dry-run] AntiPatternMemory → domain/{node_id}.md")
            return node_id

        result = actions.write_memory(meta, body)
        if result.ok:
            print(f"  [ep_writeback] ANTI hot → {node_id}")
            return node_id
        print(f"  [ep_writeback] ANTI 写入失败: {result.errors}")
        return None

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
