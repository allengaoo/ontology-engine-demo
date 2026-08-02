#!/usr/bin/env bash
# 按 stages.toml 分阶段用真实 LLM 实施 oncall（需已 init-app + inject）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a
export DEMOCODE_ALLOW_STUB="${DEMOCODE_ALLOW_STUB:-0}"

TS="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="$ROOT/logs/stages-$TS"
mkdir -p "$LOG_DIR"
echo "LOG_DIR=$LOG_DIR model=$LLM_MODEL allow_stub=$DEMOCODE_ALLOW_STUB"

python3 cli.py doctor 2>&1 | tee "$LOG_DIR/00-doctor.log"

# 极简 TOML 数组解析：读 [[stage]] 块
python3 - <<'PY' 2>&1 | tee "$LOG_DIR/01-parse-stages.log"
from pathlib import Path
import re, json
text = Path("stages.toml").read_text(encoding="utf-8")
stages = []
cur = None
for line in text.splitlines():
    if line.strip().startswith("[[stage]]"):
        if cur:
            stages.append(cur)
        cur = {}
        continue
    if cur is None:
        continue
    m = re.match(r'^(\w+)\s*=\s*"""(.*)$', line)
    if m:
        key = m.group(1)
        body = [m.group(2)] if m.group(2) else []
        if m.group(2).endswith('"""'):
            cur[key] = m.group(2)[:-3]
            continue
        # multiline
        for line2 in []:
            pass
        # consume until closing
        rest = []
        # handled below via state — simpler: use regex on full text
        cur["_ml"] = key
        cur["_buf"] = []
        continue
    if cur.get("_ml"):
        if line.strip() == '"""':
            cur[cur["_ml"]] = "\n".join(cur["_buf"]).strip()
            del cur["_ml"], cur["_buf"]
        else:
            cur["_buf"].append(line)
        continue
    m = re.match(r'^(\w+)\s*=\s*"(.*)"\s*$', line)
    if m:
        cur[m.group(1)] = m.group(2)
if cur:
    stages.append(cur)
Path("/tmp/ifclub_stages.json").write_text(json.dumps(stages, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"parsed {len(stages)} stages")
for s in stages:
    print("-", s.get("id"), s.get("title"), "task_len", len(s.get("task","")))
PY

python3 - <<'PY' 2>&1 | tee "$LOG_DIR/02-run-all-stages.log"
import json, subprocess, sys
from pathlib import Path
stages = json.loads(Path("/tmp/ifclub_stages.json").read_text(encoding="utf-8"))
log_dir = Path("""'"$LOG_DIR"'""")
# fix: use env
import os
log_dir = Path(os.environ.get("LOG_DIR", "logs/stages"))
log_dir.mkdir(parents=True, exist_ok=True)
for s in stages:
    sid = s["id"]
    task = s.get("task", "").strip()
    print("=" * 60, flush=True)
    print(f"STAGE {sid}: {s.get('title')}", flush=True)
    print("=" * 60, flush=True)
    stage_log = log_dir / f"{sid}.log"
    with open(stage_log, "w", encoding="utf-8") as lf:
        p = subprocess.run(
            [sys.executable, "cli.py", "run", "--task", task],
            stdout=lf,
            stderr=subprocess.STDOUT,
            text=True,
        )
    print(open(stage_log, encoding="utf-8").read()[-4000:])
    print(f"exit={p.returncode} log={stage_log}", flush=True)
    if p.returncode != 0:
        print(f"STOP at {sid}", flush=True)
        sys.exit(p.returncode)
    v = subprocess.run([sys.executable, "cli.py", "verify"])
    if v.returncode not in (0, 5):
        print(f"verify failed after {sid}", flush=True)
        # try fix once
        f = subprocess.run(
            [sys.executable, "cli.py", "fix", "--from-verify",
             "--task", f"修复 {sid} 验证失败，使 pytest 通过"],
        )
        v2 = subprocess.run([sys.executable, "cli.py", "verify"])
        if v2.returncode not in (0, 5):
            sys.exit(v2.returncode or 1)
print("ALL STAGES OK")
PY
