"""
LLMClient - 双路径 LLM 调用（真实 / mock fallback）

优先级：
1. 检测到 LLM_API_KEY 且 openai 包可用 → 真实 LLM（兼容 OpenAI / DeepSeek / 其他 OpenAI 兼容接口）
2. 否则 → MockAgent

.env 支持的变量：
    LLM_API_KEY   必填，API 密钥
    LLM_BASE_URL  可选，自定义接口地址（默认 https://api.openai.com/v1）
    LLM_MODEL     可选，模型名称（默认 qwen3.7）
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .mock_agent import AgentDecision, MockAgent

_ENV_LOADED = False


def _load_dotenv_once() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True

    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return

    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=False)
    except ImportError:
        # dotenv 未安装时手动解析
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value


class LLMClient:
    """统一 Agent 决策接口"""

    def __init__(self, scenario: str = "intercept_and_retry"):
        _load_dotenv_once()
        self.scenario = scenario
        self.mock_agent = MockAgent(scenario=scenario)
        self._mode = self._detect_mode()

    def _detect_mode(self) -> str:
        if os.environ.get("LLM_API_KEY"):
            try:
                import openai  # noqa: F401
                return "llm"
            except ImportError:
                print("⚠ 检测到 LLM_API_KEY，但 openai 包未安装，fallback 到 mock")
                print("  请运行: pip install openai")
        return "mock"

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def mode_label(self) -> str:
        if self._mode == "llm":
            model = os.environ.get("LLM_MODEL", "qwen3.7-plus")
            base_url = os.environ.get("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
            return f"llm ({model} @ {base_url})"
        return "mock (离线兜底)"

    def decide(
        self,
        task: str,
        tools: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentDecision:
        if self._mode == "llm":
            try:
                return self._decide_llm(task, tools, context)
            except Exception as exc:
                print(f"⚠ LLM 调用失败，fallback 到 mock: {exc}")
                return self.mock_agent.decide(task, tools, context)

        return self.mock_agent.decide(task, tools, context)

    def _decide_llm(
        self,
        task: str,
        tools: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentDecision:
        from openai import OpenAI

        api_key = os.environ["LLM_API_KEY"]
        base_url = os.environ.get("LLM_BASE_URL") or None
        model = os.environ.get("LLM_MODEL", "qwen3.7-plus")

        client = OpenAI(api_key=api_key, base_url=base_url)
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
            model=model,
            messages=messages,
            tools=openai_tools,
            tool_choice="auto",
        )

        message = response.choices[0].message
        if not message.tool_calls:
            raise RuntimeError("LLM 未返回 tool call")

        call = message.tool_calls[0]
        params = json.loads(call.function.arguments)

        return AgentDecision(
            action_id=call.function.name,
            params=params,
            reasoning=f"LLM 选择操作 {call.function.name}（模型: {model}）",
            source="llm",
        )
