#!/usr/bin/env python3
"""最终全量 30B 修复：跑 tests/meeting_order 全量，把失败文本作为 anti-hint 喂给 30B 单文件修复，循环到全绿或上限。"""

from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["LLM_MODEL"] = os.environ.get("DEMOCODE_FORCE_MODEL", "qwen3-coder-30b-a3b-instruct")

from run_meeting_sessions_30b import (  # noqa: E402
    FORCE_MODEL, WS, PATH_RULE, UNIT_HINT, SIG_HINT, _recent_anti_hint,
)


def run_pytest() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/meeting_order", "-q", "--tb=short", "-x"],
        cwd=str(WS), capture_output=True, text=True,
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return proc.returncode, out


def main() -> int:
    from cli import _build_coordinator
    from core.task import Task

    print(f"== final repair 30b  model={FORCE_MODEL} ==")
    coord, _cfg = _build_coordinator(WS, apply=True, run_pytest=True)

    max_attempts = int(os.environ.get("FINAL_REPAIR_MAX", "6"))
    for attempt in range(1, max_attempts + 1):
        rc, out = run_pytest()
        print(f"\n--- attempt {attempt}  pytest rc={rc} ---")
        if rc == 0:
            print("ALL GREEN")
            return 0
        # 抽取失败摘要给 30B
        fail_lines = [ln for ln in out.splitlines() if ln.strip().startswith(("FAILED", "E ", ">", "assert", "Error", "TypeError", "ModuleNotFoundError"))][:40]
        fail_blob = "\n".join(fail_lines) or out[-2000:]
        anti = _recent_anti_hint(WS, limit=6)
        desc = (
            f"{PATH_RULE} {UNIT_HINT} 这是最终全量修复。tests/meeting_order 跑全量时出现以下失败，"
            "只改一个跟失败最相关的源文件让它全绿（优先修被调用的实现，而不是删测试）：\n\n"
            f"失败摘要：\n{fail_blob}\n\n"
            f"已沉淀规则/ANTI（禁止重复同一错误）：\n{anti}\n\n"
            "常见根因：list_bookings 列全部时应 room_id=None 可选（不传就列全部）；"
            "测试里 patch 模块名要用 meeting_order.api.bookings（复数）不是 booking；"
            "禁止改测试去迁就错误实现，除非测试本身模块名写错。"
        )
        ctx = {
            "_session_id": "final-repair",
            "_gate_layer": "api",
            "_max_units": 1,
            "_pytest_paths": ["tests/meeting_order"],
            "_skip_pytest": False,
            "_fix_mode": True,
            "_recent_anti_hint": anti,
        }
        task = Task(description=desc, context=ctx)
        result = coord.run_ep(task, keywords=["meeting_order", "booking", "room", "fastapi", "pytest"])
        print(result.summary())
        if result.status != "completed":
            print(f"attempt {attempt} EP 未完成，继续")
    rc, out = run_pytest()
    print(f"\n== final pytest rc={rc} ==")
    print(out[-1500:])
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
