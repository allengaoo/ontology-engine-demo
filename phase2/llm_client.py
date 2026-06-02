"""
LLMClient - 双路径 LLM 调用（真实 / mock fallback）

优先级：
1. 检测到 OPENAI_API_KEY 且 openai 包可用 → 真实 LLM
2. 否则 → MockAgent
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from .mock_agent import AgentDecision, MockAgent


class LLMClient:
    """统一 Agent 决策接口"""

    def __init__(self, scenario: str = "intercept_and_retry"):
        self.scenario = scenario
        self.mock_agent = MockAgent(scenario=scenario)
        self._mode = self._detect_mode()

    def _detect_mode(self) -> str:
        if os.environ.get("OPENAI_API_KEY"):
            try:
                import openai  # noqa: F401
                return "openai"
            except ImportError:
                pass
        return "mock"

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def mode_label(self) -> str:
        if self._mode == "openai":
            return "openai (真实 LLM)"
        return "mock (离线兜底)"

    def decide(
        self,
        task: str,
        tools: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentDecision:
        if self._mode == "openai":
            try:
                return self._decide_openai(task, tools, context)
            except Exception as exc:
                print(f"⚠ LLM 调用失败，fallback 到 mock: {exc}")
                return self.mock_agent.decide(task, tools, context)

        return self.mock_agent.decide(task, tools, context)

    def _decide_openai(
        self,
        task: str,
        tools: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentDecision:
        from openai import OpenAI

        client = OpenAI()
        openai_tools = [
            {"type": t["type"], "function": t["function"]}
            for t in tools
        ]

        messages = [{"role": "user", "content": task}]
        if context and context.get("last_rejection"):
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "上一次操作被拒绝，请根据以下信息调整策略并重试：\n"
                        + json.dumps(context["last_rejection"], ensure_ascii=False)
                    ),
                }
            )

        response = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=messages,
            tools=openai_tools,
            tool_choice="required",
        )

        message = response.choices[0].message
        if not message.tool_calls:
            raise RuntimeError("LLM 未返回 tool call")

        call = message.tool_calls[0]
        params = json.loads(call.function.arguments)

        return AgentDecision(
            action_id=call.function.name,
            params=params,
            reasoning=f"OpenAI 选择操作 {call.function.name}",
            source="openai",
        )
