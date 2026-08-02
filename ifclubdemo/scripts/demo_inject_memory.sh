#!/usr/bin/env bash
# 教学：脚手架 → 注入业务记忆 → 列出记忆
set -euo pipefail
cd "$(dirname "$0")/.."

python3 cli.py init-app oncall
python3 cli.py inject docs/business_brief.md --dry-run
python3 cli.py inject docs/business_brief.md
python3 cli.py memory list

echo ""
echo "业务记忆目录:"
find workspace/oncall/.ontology_agent/memory -name '*.md' | sort
