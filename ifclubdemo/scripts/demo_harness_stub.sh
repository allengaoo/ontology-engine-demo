#!/usr/bin/env bash
# 教学：无 LLM 跑通 Harness（BSA/CA stub + 校验）
set -euo pipefail
cd "$(dirname "$0")/.."

WS="${IFCLUB_WORKSPACE:-./workspace}/harness_stub"
mkdir -p "$WS"
python3 cli.py init --workspace "$WS"
python3 cli.py run --workspace "$WS" \
  --task "修复 procurement Kafka 幂等与架构分层" \
  --no-llm --no-apply

echo "✓ stub EP 完成（未落盘）。去掉 --no-apply 可写入 $WS"
