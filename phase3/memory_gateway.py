"""
MemoryGateway — 记忆增强的 Agent 交互层

在 Phase 2 AgentGateway 基础上叠加记忆层：
  每轮决策前：检索相关记忆 + 压缩到预算内 → 注入 system context
  每轮决策后：将结果写入记忆（成功模式 → RULE 层；被拒绝 → CONTEXT 层）

三层能力在此组装：
  Retrieval   : MemoryRetriever.retrieve(intent)
  Compression : MemoryCompressor.compress(retrieval)
  Write-back  : MemoryStore.write(outcome)

不修改 Phase 1-2 的任何代码，纯中间件叠加。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
PHASE1_DIR = REPO_ROOT / "phase1"
sys.path.insert(0, str(REPO_ROOT))

from phase2.agent_gateway import AgentGateway, GatewayResponse  # noqa: E402

from .memory_store import MemoryLayer, MemoryStore
from .memory_retriever import MemoryRetriever
from .memory_compressor import MemoryCompressor, TokenBudget
from .session_manager import SessionManager


class MemoryGateway:
    """
    记忆增强的 Agent 网关

    使用方式（替换 Phase 2 的 AgentGateway）：
        gw = MemoryGateway(phase1_dir=PHASE1_DIR, memory_dir=MEMORY_DIR)
        gw.start_session("讨论认证规则调整")
        gw.chat("认证有效期从30天改为15天是否合理？")
        gw.chat("如果改了，现有哪些供应商会受影响？")
    """

    def __init__(
        self,
        phase1_dir: Optional[Path] = None,
        memory_dir: Optional[Path] = None,
        budget: Optional[TokenBudget] = None,
    ):
        self.phase1_dir = Path(phase1_dir or PHASE1_DIR)
        memory_dir = Path(memory_dir or REPO_ROOT / "phase3" / "memory_db")
        memory_dir.mkdir(parents=True, exist_ok=True)

        db_path = memory_dir / "memory.db"

        # 记忆组件
        self.memory_store     = MemoryStore(db_path)
        self.retriever        = MemoryRetriever(self.memory_store)
        self.compressor       = MemoryCompressor(budget)
        self.session_manager  = SessionManager(db_path, self.memory_store)

        # Phase 2 引擎（原有 OAG 能力不变）
        self.agent_gateway    = AgentGateway(self.phase1_dir)

        self._current_session: Optional[str] = None

    # ── 会话管理 ─────────────────────────────────────────────────────────

    def start_session(self, task: str) -> str:
        """开启新的多轮对话会话"""
        self._current_session = self.session_manager.create_session(task)
        print(f"[记忆] 会话已创建: {self._current_session}")
        print(f"[记忆] 任务: {task}")
        print(f"[记忆] CRITICAL 约束已加载: {len(self.memory_store.get_by_layer(MemoryLayer.CRITICAL))} 条")
        return self._current_session

    @property
    def current_session(self) -> Optional[str]:
        return self._current_session

    # ── 核心：记忆增强的多轮对话 ─────────────────────────────────────────

    def chat(
        self,
        user_input: str,
        verbose: bool = True,
    ) -> str:
        """
        记忆增强的单轮对话：
        1. 检索相关记忆
        2. 压缩到 Token 预算
        3. 构建 system context（记忆 + 历史）
        4. 调用 LLM（通过 AgentGateway 的 LLMClient）
        5. 将结果写回记忆

        Returns：LLM 的回复内容
        """
        if not self._current_session:
            raise RuntimeError("请先调用 start_session() 创建会话")

        # ── Step 1: 检索 ─────────────────────────────────────────────────
        retrieval = self.retriever.retrieve(user_input)
        if verbose:
            print(f"\n[记忆] {retrieval.summary()}")

        # ── Step 2: 压缩 ─────────────────────────────────────────────────
        compressed = self.compressor.compress(retrieval)
        if verbose:
            print(f"[记忆] {compressed.stats()}")

        # ── Step 3: 构建 system context ──────────────────────────────────
        memory_context = compressed.to_prompt_text()
        history_context = self.session_manager.build_history_context(self._current_session)

        system_prompt = self._build_system_prompt(memory_context, history_context)

        # ── Step 4: 调用 LLM ─────────────────────────────────────────────
        full_prompt = f"{system_prompt}\n\n用户问题：{user_input}"
        response_text = self._call_llm(full_prompt, user_input, verbose)

        # ── Step 5: 记录 turn + 写回记忆 ─────────────────────────────────
        self.session_manager.add_turn(self._current_session, "user", user_input)
        self.session_manager.add_turn(self._current_session, "assistant", response_text)

        history_tokens = self.session_manager.history_token_count(self._current_session)
        if verbose:
            print(f"[记忆] 会话历史 tokens: {history_tokens}")

        return response_text

    def execute_action_with_memory(
        self,
        task: str,
        caller: str = "memory-agent-v1",
    ) -> List[GatewayResponse]:
        """
        带记忆的 OAG 操作执行：
        在 Phase 2 的操作执行前，先检索历史决策记忆注入上下文
        执行后将结果写入 RULE/CONTEXT 层记忆
        """
        retrieval = self.retriever.retrieve(task)
        compressed = self.compressor.compress(retrieval)
        memory_context = compressed.to_prompt_text()

        print(f"[记忆增强] 注入上下文 {compressed.total_tokens} tokens")

        responses = self.agent_gateway.execute_agent_task(task, caller=caller)

        # 将执行结果写回记忆
        for resp in responses:
            if resp.status == "success":
                self._write_success_memory(resp)
            else:
                self._write_rejection_memory(resp)

        return responses

    # ── Token 统计（用于演示对比）──────────────────────────────────────

    def token_stats(self, intent: str) -> Dict[str, int]:
        """返回当前轮次的 token 分布（用于无记忆 vs 有记忆对比）"""
        retrieval = self.retriever.retrieve(intent)
        compressed = self.compressor.compress(retrieval)

        history_tokens = 0
        if self._current_session:
            history_tokens = self.session_manager.history_token_count(self._current_session)

        return {
            "memory_tokens": compressed.total_tokens,
            "history_tokens": history_tokens,
            "total_tokens": compressed.total_tokens + history_tokens,
            "critical": compressed.critical_tokens,
            "rule": compressed.rule_tokens,
            "context": compressed.context_tokens,
            "background": compressed.background_tokens,
        }

    # ── 私有方法 ─────────────────────────────────────────────────────────

    def _build_system_prompt(self, memory_context: str, history_context: str) -> str:
        parts = [
            "你是一个本体工程顾问，帮助用户分析和调整业务规则。",
            "以下是你需要遵守的约束和背景知识：",
        ]
        if memory_context:
            parts.append(memory_context)
        if history_context:
            parts.append(f"【对话历史】\n{history_context}")
        return "\n\n".join(parts)

    def _call_llm(self, full_prompt: str, user_input: str, verbose: bool) -> str:
        """调用 LLM（复用 Phase 2 的 LLMClient 双路径）"""
        from phase2.mock_agent import AgentDecision

        llm_client = self.agent_gateway.llm_client
        tools: List[Dict[str, Any]] = []  # 纯对话模式，不提供 tools

        try:
            if llm_client._mode == "llm":
                from openai import OpenAI
                import os
                client = OpenAI(
                    api_key=os.environ["LLM_API_KEY"],
                    base_url=os.environ.get("LLM_BASE_URL") or None,
                )
                model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": full_prompt}],
                )
                answer = resp.choices[0].message.content or ""
                if verbose:
                    print(f"[LLM/{model}] {answer[:200]}...")
                return answer
        except Exception as e:
            if verbose:
                print(f"[LLM] 调用失败，使用 mock 回复: {e}")

        # Mock 回复：基于关键词生成简单回复
        return self._mock_response(user_input)

    def _mock_response(self, user_input: str) -> str:
        """离线 mock 回复（用于无 API key 场景）"""
        if "30天" in user_input or "15天" in user_input or "有效期" in user_input:
            return (
                "根据现有约束，认证有效期阈值设为 30 天是为了保证采购执行时有足够的缓冲期。"
                "调整为 15 天会降低合规缓冲，建议同步更新供应商认证续期的提醒机制。"
                "注意：[CRITICAL] 约束要求认证剩余天数 >= 30 天，调整前需评估现有供应商的影响。"
            )
        if "供应商" in user_input and "影响" in user_input:
            return (
                "当前 Beta 供应商（S-BETA-002）认证剩余 13 天，调整阈值为 15 天后，"
                "Beta 仍不满足条件。ACME（S-ACME-001）认证剩余 365 天，不受影响。"
                "Gamma（S-GAMMA-003）认证剩余 60 天，调整后满足条件，但信用额度接近上限。"
            )
        return f"[Mock] 已收到：{user_input[:100]}。基于当前约束，建议审慎评估后再做调整。"

    def _write_success_memory(self, resp: GatewayResponse) -> None:
        """将成功操作写入 RULE 层记忆（成功模式沉淀）"""
        if not self._current_session:
            return
        content = (
            f"操作 {resp.action_id} 执行成功。"
            f"理由：{resp.reasoning}。"
        )
        self.memory_store.write(
            content=content,
            compressed=f"[成功] {resp.action_id}: {resp.reasoning[:60]}",
            layer=MemoryLayer.RULE,
            tags=[resp.action_id, "成功", "success"],
            source_session=self._current_session,
        )

    def _write_rejection_memory(self, resp: GatewayResponse) -> None:
        """将被拒绝操作写入 CONTEXT 层记忆（失败原因记录）"""
        if not self._current_session:
            return
        rule = resp.triggered_rule or "unknown"
        content = (
            f"操作 {resp.action_id} 被拦截，触发规则 {rule}。"
            f"建议：{resp.suggestion or '请检查参数'}。"
        )
        self.memory_store.write(
            content=content,
            compressed=f"[拒绝] {resp.action_id} 触发 {rule}",
            layer=MemoryLayer.CONTEXT,
            tags=[resp.action_id, rule, "拒绝", "rejected"],
            source_session=self._current_session,
        )
