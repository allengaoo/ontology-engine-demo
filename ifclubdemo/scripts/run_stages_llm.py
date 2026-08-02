#!/usr/bin/env python3
"""按 stages.toml 分阶段调用 cli.py run（真实 LLM）。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_stages(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    stages: list[dict] = []
    cur: dict | None = None
    ml_key: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("[[stage]]"):
            if cur is not None:
                stages.append(cur)
            cur = {}
            ml_key = None
            buf = []
            continue
        if cur is None:
            continue
        if ml_key is not None:
            if line.strip() == '"""':
                cur[ml_key] = "\n".join(buf).strip()
                ml_key = None
                buf = []
            else:
                buf.append(line)
            continue
        m = re.match(r'^(\w+)\s*=\s*"""(.*)$', line)
        if m:
            key, first = m.group(1), m.group(2)
            if first.endswith('"""'):
                cur[key] = first[:-3]
            else:
                ml_key = key
                buf = [first] if first else []
            continue
        m = re.match(r'^(\w+)\s*=\s*"(.*)"\s*$', line)
        if m:
            cur[m.group(1)] = m.group(2)
    if cur is not None:
        stages.append(cur)
    return stages


def main() -> int:
    os.chdir(ROOT)
    os.environ.setdefault("DEMOCODE_ALLOW_STUB", "0")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir = ROOT / "logs" / f"stages-{ts}"
    log_dir.mkdir(parents=True, exist_ok=True)

    stages = parse_stages(ROOT / "stages.toml")
    (log_dir / "stages.json").write_text(
        json.dumps(stages, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"LOG_DIR={log_dir} stages={len(stages)} model={os.environ.get('LLM_MODEL')}")

    subprocess.run([sys.executable, "cli.py", "doctor"], check=False)

    for s in stages:
        sid = s.get("id", "EP?")
        task = (s.get("task") or "").strip()
        print("=" * 60)
        print(f"STAGE {sid}: {s.get('title')}")
        print("=" * 60)
        stage_log = log_dir / f"{sid}.log"
        cmd = [sys.executable, "cli.py", "run", "--task", task]
        tests = (s.get("tests") or "").strip()
        if tests:
            cmd.extend(["--tests", tests])
        with stage_log.open("w", encoding="utf-8") as lf:
            p = subprocess.run(
                cmd,
                stdout=lf,
                stderr=subprocess.STDOUT,
            )
        print(stage_log.read_text(encoding="utf-8")[-5000:])
        print(f"exit={p.returncode} log={stage_log}")
        if p.returncode != 0:
            print(f"STOP at {sid} (run failed)")
            return p.returncode

        verify_cmd = [sys.executable, "cli.py", "verify"]
        if tests:
            verify_cmd.extend(["--tests", tests])
        v = subprocess.run(verify_cmd)
        if v.returncode not in (0, 5):
            print(f"verify failed after {sid}, trying fix…")
            fix_cmd = [
                sys.executable,
                "cli.py",
                "fix",
                "--from-verify",
                "--task",
                f"修复 {sid} 验证失败，使 pytest 通过；对齐已有 oncall API",
            ]
            if tests:
                fix_cmd.extend(["--tests", tests])
            subprocess.run(fix_cmd)
            v2 = subprocess.run(verify_cmd)
            if v2.returncode not in (0, 5):
                print(f"STOP at {sid} (verify failed)")
                return v2.returncode or 1

    print("ALL STAGES OK")
    (log_dir / "DONE").write_text("ok\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
