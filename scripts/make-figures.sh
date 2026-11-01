#!/usr/bin/env bash
#
# Phase 7: ensure plotting deps, then render figures/fig07..fig12*.pdf from
# the CSVs produced by scripts/collect-sweeps.py.
#
# Usage:  scripts/make-figures.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -f "$ROOT/results/sweeps/fig08_pareto.csv" ]; then
    echo "error: run scripts/collect-sweeps.py first" >&2
    exit 1
fi

bash "$ROOT/scripts/setup-plot-deps.sh" >/dev/null
mkdir -p "$ROOT/figures"
"$ROOT/.venv/bin/python" "$ROOT/scripts/plot-sweeps.py"
