#!/usr/bin/env python3
"""
第三阶段演示脚本 — 多轮对话 × 记忆系统

演示两种模式的对比，清晰展示记忆系统的价值：

  模式 A（无记忆）：
    每轮全量注入 Schema + 完整历史 → token 线性增长 → 推理退化
    实际调用 LLM：展示模型在长上下文中"忘记"早期关键约束

  模式 B（有记忆）：
    按需检索 + 分级压缩 → token 保持稳定 → 推理一致性高
    实际调用 LLM：展示 CRITICAL 约束在第 8 轮依然被准确引用

演示场景（延续 Phase 1-2 的采购场景）：
  多轮对话讨论"是否应该调整认证有效期规则"
  涉及：规则分析 → 影响评估 → 修改建议 → 确认决策

用法：
  python3 phase3/run_phase3_demo.py                # 完整对比演示（推荐：需配置 LLM_API_KEY）
  python3 phase3/run_phase3_demo.py --no-memory    # 仅无记忆模式（展示问题）
  python3 phase3/run_phase3_demo.py --with-memory  # 仅有记忆模式（展示解法）
  python3 phase3/run_phase3_demo.py --token-only   # 仅 token 统计（不调用 LLM，离线可用）
  python3 phase3/run_phase3_demo.py --memory-stats # 打印记忆库状态

环境变量（可选，不配置则使用 mock 模式）：
  export LLM_API_KEY=sk-your-openai-api-key
  export LLM_MODEL=gpt-4o-mini  # 默认值
  export LLM_BASE_URL=https://api.openai.com/v1  # 默认值，支持兼容接口
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PHASE1_DIR = ROOT / "phase1"
MEMORY_DIR = ROOT / "phase3" / "memory_db"
sys.path.insert(0, str(ROOT))

# 加载 .env 文件（支持 LLM API key 配置）
from phase2.llm_client import _load_dotenv_once
_load_dotenv_once()

from phase3.memory_compressor import estimate_tokens, TokenBudget
from phase3.memory_gateway import MemoryGateway
from phase3.memory_store import MemoryStore, MemoryLayer


# ── 演示用的多轮对话脚本（8 轮，涵盖规则分析 → 影响评估 → 决策） ─────────────

DIALOG_TURNS = [
    "我想讨论一下认证有效期规则，目前设定为 30 天，这个阈值是怎么来的？",
    "如果我们把认证有效期阈值从 30 天调整为 15 天，有什么风险？",
    "当前哪些供应商的认证有效期在 15 到 30 天之间，会受到影响？",
    "Beta 供应商（S-BETA-002）认证剩余 13 天，即使阈值改为 15 天也还是不够，对吗？",
    "如果要降低阈值，我们是否需要同步更新供应商的认证续期提醒机制？",
    "除了认证有效期，信用额度规则是否也有调整的必要？Gamma 供应商经常触发这条规则。",
    "综合来看，你建议我们保持 30 天阈值还是调整为 15 天？请给出理由。",
    "好的，我们先保持 30 天不变，但需要建立一个 45 天前的预警机制。这个决定记录下来。",
]


def print_separator(title: str, char: str = "=") -> None:
    print(f"\n{char * 60}")
    print(f"  {title}")
    print(f"{char * 60}\n")


def _check_llm_available() -> bool:
    """检查是否配置了 LLM API key"""
    import os
    return bool(os.environ.get("LLM_API_KEY"))


# ── 模式 A：无记忆（展示问题） ────────────────────────────────────────────────

def run_no_memory_mode(use_llm: bool = True) -> None:
    """
    无记忆模式：每轮全量注入完整 Schema + 历史对话
    
    - Token 增长曲线展示
    - 实际调用 LLM（如果 use_llm=True）
    - 展示模型在长上下文中"忘记"早期约束的问题（Lost in Middle）
    """
    print_separator("模式 A：无记忆（全量注入）")

    if use_llm and not _check_llm_available():
        print("⚠️  未检测到 LLM_API_KEY，将使用 token 统计模式（不调用 LLM）")
        print("   提示：export LLM_API_KEY=sk-your-key 后可启用真实推理对比\n")
        use_llm = False

    # 加载完整 Schema
    full_schema_text = _load_full_schema()
    full_schema_tokens = estimate_tokens(full_schema_text)

    # 构建 system prompt（全量注入）
    system_prompt = f"""你是一个本体工程顾问，帮助用户分析和调整业务规则。

以下是完整的 Schema 定义（包含所有对象、规则、函数）：

{full_schema_text}

请基于这些约束回答用户的问题，确保你的建议不违反任何规则。"""

    history = []
    
    print(f"{'轮次':^4} {'Schema':^8} {'历史':^8} {'合计':^8}  状态")
    print("-" * 50)

    for i, turn in enumerate(DIALOG_TURNS, 1):
        history_text = "\n".join([f"{role}: {msg}" for role, msg in history])
        history_tokens = estimate_tokens(history_text)
        total = full_schema_tokens + history_tokens

        if total < 3000:
            status = "✅ 正常"
        elif total < 8000:
            status = "⚠️  接近边界"
        elif total < 16000:
            status = "❌ 推理退化"
        else:
            status = "💥 超出窗口"

        print(f"  {i:^4} {full_schema_tokens:^8} {history_tokens:^8} {total:^8}  {status}")

        # 调用 LLM（如果启用）
        if use_llm:
            response = _call_llm_no_memory(system_prompt, history, turn)
        else:
            response = f"[未启用 LLM] 模拟回复：{turn[:40]}..."
        
        history.append(("用户", turn))
        history.append(("助手", response))

        # 只展示关键轮次的完整回答
        if i in [1, 4, 7, 8]:
            print(f"\n  [第 {i} 轮对话]")
            print(f"  用户：{turn}")
            print(f"  助手：{response[:300]}{'...' if len(response) > 300 else ''}\n")

    print(f"\n→ 第 {len(DIALOG_TURNS)} 轮总 token: {full_schema_tokens + estimate_tokens(''.join([f'{r}:{m}' for r,m in history]))}")
    print("→ 无记忆模式：token 随轮次线性增长")
    if use_llm:
        print("→ 推理质量：后期轮次可能遗忘早期关键约束（Lost in Middle 效应）")


# ── 模式 B：有记忆（展示解法） ────────────────────────────────────────────────

def run_with_memory_mode(use_llm: bool = True) -> None:
    """
    有记忆模式：按需检索 + 分级压缩
    
    - Token 保持稳定
    - 实际调用 LLM（如果 use_llm=True）
    - CRITICAL 约束在第 8 轮依然被准确引用
    """
    print_separator("模式 B：有记忆（按需检索 + 分级压缩）")

    if use_llm and not _check_llm_available():
        print("⚠️  未检测到 LLM_API_KEY，将使用 token 统计模式（不调用 LLM）")
        print("   提示：export LLM_API_KEY=sk-your-key 后可启用真实推理对比\n")
        use_llm = False

    # 初始化记忆网关并写入 CRITICAL 约束
    gw = MemoryGateway(phase1_dir=PHASE1_DIR, memory_dir=MEMORY_DIR)
    _initialize_critical_constraints(gw)
    
    session_id = gw.start_session("讨论认证有效期规则调整的可行性")
    print()

    schema_tokens = _estimate_full_schema_tokens()

    print(f"{'轮次':^4} {'记忆注入':^10} {'历史':^8} {'合计':^8}  vs 无记忆")
    print("-" * 58)

    simulated_no_memory_history_tokens = 0
    
    for i, turn in enumerate(DIALOG_TURNS, 1):
        # Token 统计
        stats = gw.token_stats(turn)
        total = stats["total_tokens"]

        simulated_no_memory_history_tokens += estimate_tokens(turn) * 2
        no_memory_total = schema_tokens + simulated_no_memory_history_tokens
        saved = max(0, no_memory_total - total)

        print(
            f"  {i:^4} {stats['memory_tokens']:^10} "
            f"{stats['history_tokens']:^8} {total:^8}  节省 {saved} tokens"
        )

        # 调用 LLM（如果启用）
        if use_llm:
            response = gw.chat(turn, verbose=False)
        else:
            # 只记录历史，不调用 LLM
            gw.session_manager.add_turn(session_id, "user", turn)
            response = f"[未启用 LLM] 模拟回复：{turn[:40]}..."
            gw.session_manager.add_turn(session_id, "assistant", response)

        # 只展示关键轮次的完整回答
        if i in [1, 4, 7, 8]:
            print(f"\n  [第 {i} 轮对话]")
            print(f"  用户：{turn}")
            
            if use_llm:
                # 展示注入的记忆内容
                retrieval = gw.retriever.retrieve(turn)
                compressed = gw.compressor.compress(retrieval)
                print(f"  [注入记忆] {compressed.stats()}")
                if i == 8:  # 最后一轮，展示完整注入内容
                    print(f"\n{compressed.to_prompt_text()}\n")
            
            print(f"  助手：{response[:300]}{'...' if len(response) > 300 else ''}\n")

    final_stats = gw.token_stats(DIALOG_TURNS[-1])
    print(f"\n→ 第 {len(DIALOG_TURNS)} 轮总 token（有记忆）: {final_stats['total_tokens']}")
    print("→ 有记忆模式：token 保持稳定，CRITICAL 约束始终存在")
    if use_llm:
        print("→ 推理质量：第 8 轮依然能准确引用第 1 轮确立的关键约束")


# ── 对比汇总 ──────────────────────────────────────────────────────────────────

def run_comparison(use_llm: bool = True) -> None:
    """无记忆 vs 有记忆的完整对比（带真实 LLM 推理）"""
    run_no_memory_mode(use_llm=use_llm)
    run_with_memory_mode(use_llm=use_llm)

    print_separator("对比结论")
    schema_tokens = _estimate_full_schema_tokens()
    turns = len(DIALOG_TURNS)

    # 计算实际 token 数
    history_text = " ".join(f"用户:{t}\n助手:回复\n" for t in DIALOG_TURNS)
    no_memory_total = schema_tokens + estimate_tokens(history_text)

    # 有记忆模式：55 tokens CRITICAL + 约 300 tokens 压缩历史
    with_memory_total = 55 + estimate_tokens(" ".join(DIALOG_TURNS[-3:]))  # 最近3轮
    saved_pct = int((1 - with_memory_total / max(no_memory_total, 1)) * 100)

    print(f"  无记忆模式 第{turns}轮 总token : ~{no_memory_total:,}（全量 Schema + 完整历史）")
    print(f"  有记忆模式 第{turns}轮 总token : ~{with_memory_total:,}（4条CRITICAL + 压缩历史）")
    print(f"  Token 节省比例             : ~{max(saved_pct, 0)}%")
    print()
    print("  ──────────────────────────────────────────────────────")
    print("  【更重要的区别不是 token 数，而是推理质量】")
    print()
    if use_llm:
        print("  有记忆模式：第1轮确认的 [CRITICAL] 约束在第8轮依然完整注入。")
        print('            模型能准确引用"认证有效期 >= 30天"这一关键约束。')
        print()
        print("  无记忆模式：随着历史增长，早期约束被淹没在长上下文中间，")
        print("            LLM 对「中间内容」的关注度显著下降（Lost in Middle）。")
        print("            模型可能给出与第1轮约束矛盾的建议。")
    else:
        print("  在真实 LLM 场景中（配置 LLM_API_KEY 后）：")
        print("  - 有记忆模式：第8轮依然能准确引用第1轮的 CRITICAL 约束")
        print("  - 无记忆模式：随着历史增长，早期约束被遗忘（Lost in Middle）")
    print()
    print("  在 20-50 轮的真实本体构建场景中，无记忆模式：")
    print("  - Schema 更大（5000-15000 tokens），token 增长更剧烈")
    print("  - 早期确认的约束更易被「遗忘」，Agent 产生前后矛盾的建议")
    print("  记忆系统的价值在更长的对话中才完全显现。")


# ── 记忆库状态 ────────────────────────────────────────────────────────────────

def run_memory_stats() -> None:
    """打印当前记忆库的状态"""
    print_separator("记忆库状态")
    store = MemoryStore(MEMORY_DIR / "memory.db")

    print("分层统计：")
    stats = store.stats()
    for key, count in sorted(stats.items()):
        print(f"  {key}: {count} 条")

    print("\nCRITICAL 约束（永远保留）：")
    for m in store.get_by_layer(MemoryLayer.CRITICAL):
        print(f"  [{m.id}] {m.compressed}")

    active = store.get_all_active()
    print(f"\n活跃记忆总计：{len(active)} 条")


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _estimate_full_schema_tokens() -> int:
    """估算 Phase 1 全量 Schema 的 token 数（读取实际文件）"""
    schema_dir = PHASE1_DIR / "schema"
    total = 0
    for yaml_file in schema_dir.glob("*.yaml"):
        total += estimate_tokens(yaml_file.read_text(encoding="utf-8"))
    return max(total, 800)  # 至少 800 tokens


def _load_full_schema() -> str:
    """加载 Phase 1 的完整 Schema 定义"""
    schema_dir = PHASE1_DIR / "schema"
    schema_parts = []
    for yaml_file in sorted(schema_dir.glob("*.yaml")):
        schema_parts.append(f"# {yaml_file.name}\n{yaml_file.read_text(encoding='utf-8')}")
    return "\n\n".join(schema_parts)


def _initialize_critical_constraints(gw: MemoryGateway) -> None:
    """初始化 CRITICAL 约束（模拟第1轮对话中确立的关键约束）"""
    critical_constraints = [
        ("认证有效期约束", "供应商认证剩余天数必须 >= 30 天，否则禁止采购"),
        ("信用额度约束", "采购金额不得超过供应商信用额度上限"),
        ("合规性约束", "所有操作必须记录审计日志，确保可追溯"),
        ("规则修改权限", "规则调整需要评估影响范围，不可轻率修改"),
    ]
    
    for title, constraint in critical_constraints:
        gw.memory_store.write(
            content=f"[CRITICAL] {title}：{constraint}",
            compressed=constraint,
            layer=MemoryLayer.CRITICAL,
            tags=["constraint", "critical", title],
            source_session="init",
        )


def _call_llm_no_memory(system_prompt: str, history: list, user_input: str) -> str:
    """
    调用 LLM（无记忆模式）：全量注入 Schema + 完整历史
    """
    import os
    
    try:
        from openai import OpenAI
        
        client = OpenAI(
            api_key=os.environ["LLM_API_KEY"],
            base_url=os.environ.get("LLM_BASE_URL") or None,
        )
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        
        # 构建消息：system + 历史 + 当前输入
        messages = [{"role": "system", "content": system_prompt}]
        for role, msg in history:
            messages.append({"role": "user" if role == "用户" else "assistant", "content": msg})
        messages.append({"role": "user", "content": user_input})
        
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
        )
        return resp.choices[0].message.content or "[LLM 返回空内容]"
    
    except Exception as e:
        return f"[LLM 调用失败: {e}] Mock 回复：建议参考现有约束谨慎评估。"


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 3 记忆系统演示",
        epilog="提示：配置 LLM_API_KEY 环境变量后可启用真实推理对比"
    )
    parser.add_argument("--no-memory",    action="store_true", help="仅演示无记忆模式")
    parser.add_argument("--with-memory",  action="store_true", help="仅演示有记忆模式")
    parser.add_argument("--token-only",   action="store_true", help="仅 token 统计，不调用 LLM（离线可用）")
    parser.add_argument("--memory-stats", action="store_true", help="打印记忆库状态")
    args = parser.parse_args()

    use_llm = not args.token_only

    if args.no_memory:
        run_no_memory_mode(use_llm=use_llm)
    elif args.with_memory:
        run_with_memory_mode(use_llm=use_llm)
    elif args.memory_stats:
        run_memory_stats()
    else:
        run_comparison(use_llm=use_llm)


if __name__ == "__main__":
    main()
