#!/usr/bin/env bash
# 教学：检查 .env / LLM / workspace
set -euo pipefail
cd "$(dirname "$0")/.."
python3 cli.py doctor
