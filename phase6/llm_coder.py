"""
llm_coder — 端侧小模型编码调用器

职责：
  - 将 InjectManifest 组装为 system prompt + user task
  - 调用 qwen3-32b（DashScope 兼容 OpenAI 接口）
  - 返回生成的代码 + 原始 response 供校验

设计选择：
  - 关闭 thinking（/no_think）模拟端侧 token 约束
  - system prompt 仅包含 InjectManifest 的 context_text（记忆注入）
  - 模型不带工具，纯文本生成（编码任务）
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from memory_injector import InjectManifest


@dataclass
class CodeGenResult:
    code: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    raw_content: str
    success: bool
    error: Optional[str] = None


def load_env(env_path: Optional[Path] = None) -> None:
    """手动解析 .env 文件（避免强依赖 python-dotenv）"""
    if env_path is None:
        env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


SYSTEM_TEMPLATE = """\
你是一个端侧编码助手。下面是与当前任务相关的记忆上下文（由记忆本体内核注入）。
请严格遵守 ConstraintMemory 中的硬约束，参考 PatternMemory 和 DecisionRecord 的经验。

--- 记忆上下文（InjectManifest）---
{context}
--- 结束 ---

要求：
1. 只输出 Python 代码（用 ```python 包裹）
2. 遵守所有 enforcement=reject 的约束
3. 如引用了记忆中的经验，在代码注释中标注记忆 ID
"""


class LLMCoder:
    def __init__(self, model: str = "qwen3-32b"):
        load_env()
        self.api_key = os.environ.get("LLM_API_KEY", "")
        self.base_url = os.environ.get(
            "LLM_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.model = model

    def generate(self, manifest: InjectManifest, task: str) -> CodeGenResult:
        if not self.api_key:
            return CodeGenResult(
                code="", model=self.model,
                prompt_tokens=0, completion_tokens=0,
                raw_content="", success=False,
                error="LLM_API_KEY 未设置",
            )

        try:
            from openai import OpenAI
        except ImportError:
            return CodeGenResult(
                code="", model=self.model,
                prompt_tokens=0, completion_tokens=0,
                raw_content="", success=False,
                error="openai 包未安装，请运行 pip install openai",
            )

        system_msg = SYSTEM_TEMPLATE.format(context=manifest.context_text)
        user_msg = f"任务：{task}\n\n请根据上面的记忆上下文，给出修复代码。"

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.3,
                max_tokens=2048,
                extra_body={"enable_thinking": False},
            )
        except Exception as exc:
            return CodeGenResult(
                code="", model=self.model,
                prompt_tokens=0, completion_tokens=0,
                raw_content="", success=False,
                error=f"LLM 调用失败: {exc}",
            )

        content = response.choices[0].message.content or ""
        usage = response.usage
        code = self._extract_code(content)

        return CodeGenResult(
            code=code,
            model=self.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            raw_content=content,
            success=True,
        )

    @staticmethod
    def _extract_code(content: str) -> str:
        """从 markdown 代码块中提取 Python 代码"""
        import re
        pattern = r"```(?:python)?\s*\n(.*?)```"
        matches = re.findall(pattern, content, re.DOTALL)
        if matches:
            return matches[0].strip()
        return content.strip()
