"""
MockAgent - 离线兜底 Agent

当没有 LLM API key 或调用失败时使用。
按预设任务序列选择操作和参数，输出与真实 LLM 路径同构的结构。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class AgentDecision:
    action_id: str
    params: Dict[str, Any]
    reasoning: str
    source: str = "mock"


class MockAgent:
    """内置 mock Agent，演示拦截与重试闭环"""

    def __init__(self, scenario: str = "intercept_and_retry"):
        self.scenario = scenario
        self._step = 0

    @property
    def mode_label(self) -> str:
        return "mock"

    def decide(
        self,
        task: str,
        tools: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentDecision:
        context = context or {}

        if self.scenario == "intercept_and_retry":
            return self._intercept_and_retry(task, context)

        # 默认：向 ACME 正常采购
        return AgentDecision(
            action_id="create_purchase_order",
            params={
                "supplier_pk": "S-ACME-001",
                "material": "精密轴承",
                "amount": 280000,
                "quantity": 1000,
            },
            reasoning="Mock：向认证有效的 ACME 发起采购",
        )

    def _intercept_and_retry(self, task: str, context: Dict[str, Any]) -> AgentDecision:
        last_rejection = context.get("last_rejection")

        if last_rejection:
            suggestion = last_rejection.get("suggestion", "")
            if "ACME" in suggestion or "S-ACME-001" in suggestion:
                return AgentDecision(
                    action_id="create_purchase_order",
                    params={
                        "supplier_pk": "S-ACME-001",
                        "material": "工业胶水",
                        "amount": 80000,
                        "quantity": 500,
                    },
                    reasoning="Mock：收到拒绝响应后，改选认证有效的 ACME 重试",
                )

        if self._step == 0:
            self._step += 1
            return AgentDecision(
                action_id="create_purchase_order",
                params={
                    "supplier_pk": "S-BETA-002",
                    "material": "工业胶水",
                    "amount": 80000,
                    "quantity": 500,
                },
                reasoning="Mock：首次尝试向 Beta 采购（预期被认证规则拦截）",
            )

        return AgentDecision(
            action_id="create_purchase_order",
            params={
                "supplier_pk": "S-ACME-001",
                "material": "精密轴承",
                "amount": 280000,
                "quantity": 1000,
            },
            reasoning="Mock：fallback 到 ACME 正常采购",
        )
