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
bash tests/run_golden.sh >/dev/null
bash tests/run_edge_cases.sh >/dev/null
if [ "${SANITIZE:-0}" = "1" ]; then
  bash tests/run_sanitizer.sh >/dev/null
fi
bash scripts/run-baselines.sh "${1:-4}"
python3 scripts/collect.py
python3 scripts/markov-threshold.py >/dev/null
if [ "${RUN_PHASE9:-1}" = "1" ]; then
  bash scripts/phase9-simulation.sh >/dev/null
fi
echo "run-all: DONE -> results/baselines/baseline_results.csv, results/theory/markov_threshold.csv, results/phase9/section55.csv"
