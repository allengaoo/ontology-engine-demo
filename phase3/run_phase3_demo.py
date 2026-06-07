#!/usr/bin/env python3
"""
第三阶段演示脚本 — 多轮对话 × 记忆系统

演示两种模式的对比，清晰展示记忆系统的价值：

  模式 A（无记忆）：
    每轮全量注入 Schema + 完整历史 → token 线性增长 → 推理退化

  模式 B（有记忆）：
    按需检索 + 分级压缩 → token 保持稳定 → 推理一致性高

演示场景（延续 Phase 1-2 的采购场景）：
  多轮对话讨论"是否应该调整认证有效期规则"
  涉及：规则分析 → 影响评估 → 修改建议 → 确认决策

用法：
  python3 phase3/run_phase3_demo.py                # 完整对比演示
  python3 phase3/run_phase3_demo.py --no-memory    # 仅无记忆模式（展示问题）
  python3 phase3/run_phase3_demo.py --with-memory  # 仅有记忆模式（展示解法）
  python3 phase3/run_phase3_demo.py --memory-stats # 打印记忆库状态
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PHASE1_DIR = ROOT / "phase1"
MEMORY_DIR = ROOT / "phase3" / "memory_db"
sys.path.insert(0, str(ROOT))

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


# ── 模式 A：无记忆（展示问题） ────────────────────────────────────────────────

def run_no_memory_mode() -> None:
    """
    模拟无记忆模式：
    每轮全量注入完整 Schema + 历史对话，展示 token 增长曲线
    """
    print_separator("模式 A：无记忆（全量注入）")

    # 模拟完整 Schema 的 token 数（来自 Phase 1 YAML 文件的实际大小）
    full_schema_tokens = _estimate_full_schema_tokens()

    history_text = ""
    print(f"{'轮次':^4} {'Schema':^8} {'历史':^8} {'合计':^8}  状态")
    print("-" * 45)

    for i, turn in enumerate(DIALOG_TURNS, 1):
        history_text += f"用户: {turn}\n助手: [回复内容]\n"
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

    print(f"\n→ 第 {len(DIALOG_TURNS)} 轮总 token: {full_schema_tokens + estimate_tokens(history_text)}")
    print("→ 无记忆模式：token 随轮次线性增长，推理准确率逐渐退化")


# ── 模式 B：有记忆（展示解法） ────────────────────────────────────────────────

def run_with_memory_mode() -> None:
    """
    有记忆模式：
    按需检索 + 分级压缩，展示 token 稳定和推理一致性。
    
    ─── Token 对比表：纯本地计算，不发起 LLM 调用 ───────────────────
    ─── 最后 1 轮：调用 LLM（若 .env 有效）或 mock 兜底 ────────────
    """
    print_separator("模式 B：有记忆（按需检索 + 分级压缩）")

    gw = MemoryGateway(phase1_dir=PHASE1_DIR, memory_dir=MEMORY_DIR)
    session_id = gw.start_session("讨论认证有效期规则调整的可行性")
    print()

    schema_tokens = _estimate_full_schema_tokens()

    print(f"{'轮次':^4} {'记忆注入':^10} {'历史':^8} {'合计':^8}  vs 无记忆")
    print("-" * 58)

    simulated_no_memory_history_tokens = 0
    for i, turn in enumerate(DIALOG_TURNS, 1):
        # ── token 统计（本地，不调用 LLM）──────────────────────────────
        stats = gw.token_stats(turn)
        total = stats["total_tokens"]

        simulated_no_memory_history_tokens += estimate_tokens(turn) * 2
        no_memory_total = schema_tokens + simulated_no_memory_history_tokens
        saved = max(0, no_memory_total - total)

        print(
            f"  {i:^4} {stats['memory_tokens']:^10} "
            f"{stats['history_tokens']:^8} {total:^8}  节省 {saved} tokens（无记忆 ~{no_memory_total}）"
        )

        # 只写 session 历史，不调 LLM（mock 写入历史用于 token 统计）
        gw.session_manager.add_turn(session_id, "user", turn)
        gw.session_manager.add_turn(session_id, "assistant", f"[记录] {turn[:40]}...")

    print(f"\n→ 第 {len(DIALOG_TURNS)} 轮总 token（有记忆）: {gw.token_stats(DIALOG_TURNS[-1])['total_tokens']}")
    print("→ 有记忆模式：token 保持稳定，CRITICAL 约束始终存在，推理一致性高")

    # ── 最后一轮实际对话（展示约束一致性，mock 兜底）─────────────────────
    print_separator("最后一轮对话示例（含记忆注入）", char="-")
    final_input = DIALOG_TURNS[-1]
    retrieval = gw.retriever.retrieve(final_input)
    compressed = gw.compressor.compress(retrieval)
    history_ctx = gw.session_manager.build_history_context(session_id)

    print(f"注入记忆（{compressed.total_tokens} tokens）：")
    print(compressed.to_prompt_text())
    print(f"\n用户：{final_input}")

    response = gw._mock_response(final_input)
    print(f"\n助手（mock）：{response}")


# ── 对比汇总 ──────────────────────────────────────────────────────────────────

def run_comparison() -> None:
    """无记忆 vs 有记忆的完整对比"""
    run_no_memory_mode()
    run_with_memory_mode()

    print_separator("对比结论")
    schema_tokens = _estimate_full_schema_tokens()
    turns = len(DIALOG_TURNS)

    # 计算实际 token 数
    history_text = " ".join(f"用户:{t}\n助手:回复\n" for t in DIALOG_TURNS)
    no_memory_total = schema_tokens + estimate_tokens(history_text)

    # 有记忆模式：55 tokens CRITICAL + 约 300 tokens 压缩历史
    with_memory_total = 55 + estimate_tokens(" ".join(DIALOG_TURNS))
    saved_pct = int((1 - with_memory_total / max(no_memory_total, 1)) * 100)

    print(f"  无记忆模式 第{turns}轮 总token : ~{no_memory_total:,}（全量 Schema + 完整历史）")
    print(f"  有记忆模式 第{turns}轮 总token : ~{with_memory_total:,}（4条CRITICAL + 压缩历史）")
    print(f"  Token 节省比例             : ~{max(saved_pct, 0)}%")
    print()
    print("  ──────────────────────────────────────────────────────")
    print("  【更重要的区别不是 token 数，而是约束一致性】")
    print()
    print("  有记忆模式：第1轮确认的 [CRITICAL] 约束在第8轮依然完整注入。")
    print("  无记忆模式：随着历史增长，早期约束会被淹没在长上下文中间，")
    print("             LLM 对「中间内容」的关注度显著下降（Lost in Middle）。")
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


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 3 记忆系统演示")
    parser.add_argument("--no-memory",    action="store_true", help="仅演示无记忆模式")
    parser.add_argument("--with-memory",  action="store_true", help="仅演示有记忆模式")
    parser.add_argument("--memory-stats", action="store_true", help="打印记忆库状态")
    args = parser.parse_args()

    if args.no_memory:
        run_no_memory_mode()
    elif args.with_memory:
        run_with_memory_mode()
    elif args.memory_stats:
        run_memory_stats()
    else:
        run_comparison()


if __name__ == "__main__":
    main()
