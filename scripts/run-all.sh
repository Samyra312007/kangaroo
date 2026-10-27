#!/usr/bin/env bash
# One-command reproduction: build, generate baselines, run, collect.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
bash scripts/setup-deps.sh >/dev/null
bash scripts/build.sh >/dev/null
# regenerate baseline configs if missing
if [ ! -d configs/baselines ] || [ -z "$(ls configs/baselines 2>/dev/null)" ]; then
  mkdir -p configs/baselines
  # configs are committed; nothing to generate beyond what's in tree
fi
bash scripts/run-baselines.sh "${1:-4}"
python3 scripts/collect.py
echo "run-all: DONE -> results/baselines/baseline_results.csv"
