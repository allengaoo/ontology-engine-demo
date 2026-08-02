"""
memory_writeback — Agent 回合输出写回联邦记忆图（Phase 7 P0）

将 Agent 执行结果写入 DecisionRecord 实例，经过 OntologyRegistry 校验。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_actions import MemoryActions


class MemoryWriteback:
    """按 Agent scope 将回合输出写入对应域的 instances 目录。"""

    def __init__(self, actions_by_domain: Dict[str, MemoryActions]):
        self.actions_by_domain = actions_by_domain

    def record_turn(
        self,
        agent_name: str,
        write_layers: List[str],
        primary_domain: str,
        task_description: str,
        memory_ids: List[str],
        agent_output: Any,
        dry_run: bool = False,
    ) -> Optional[str]:
        """
        写入一条 DecisionRecord。返回 node_id；dry_run 时只打印不写盘。
        """
        if not write_layers:
            return None

        actions = self.actions_by_domain.get(primary_domain)
        if actions is None:
            print(f"  [writeback] 跳过：域 {primary_domain} 无 MemoryActions")
            return None

        now = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        node_id = f"DEC-{agent_name}-{now}"
        output_text = (
            json.dumps(agent_output, ensure_ascii=False, indent=2)
            if isinstance(agent_output, (dict, list))
            else str(agent_output)
        )

        meta = {
            "id": node_id,
            "object_type": "DecisionRecord",
            "title": f"{agent_name} 回合输出",
            "layer": "DOMAIN",
            "tier": "warm",
            "tags": ["agent-output", agent_name.lower(), primary_domain],
            "confidence": 0.9,
            "schema_version": 2,
            "context": task_description[:500],
            "decision": output_text[:2000],
            "about_concepts": ["agent-turn", primary_domain],
            "derived_from": memory_ids[:10],
            "status": "active",
        }

        body = (
            f"## 背景\n\n"
            f"Agent={agent_name}  domain={primary_domain}  write_layers={write_layers}\n\n"
            f"## 决策\n\n"
            f"{output_text[:1500]}\n\n"
            f"## 备选\n\n"
            f"注入记忆：{memory_ids}\n"
        )

        if dry_run:
            print(f"  [writeback/dry-run] 将写入 {primary_domain}/{node_id}.md")
            return node_id

        result = actions.write_memory(meta, body)
        if result.ok:
            return node_id
        print(f"  [writeback] 校验失败: {result.errors}")
        return None
