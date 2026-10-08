#!/usr/bin/env bash
#
# Phase 1: run the SA and LS baseline configurations and capture their summary
# output. Each run's stdout/stderr is saved to results/baselines/logs/<name>.log.
#
# Usage:  scripts/run-baselines.sh [JOBS]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIM="$ROOT/third_party/Kangaroo/simulator"
RUNDIR="$ROOT/third_party/Kangaroo/run-scripts"
CFGDIR="$ROOT/configs/baselines"
OUTDIR="$ROOT/results/baselines/logs"
JOBS="${1:-8}"

BIN="$SIM/bin/cache"
if [ ! -x "$BIN" ]; then
    echo "error: $BIN not found; run scripts/build.sh first" >&2
    exit 1
fi

mkdir -p "$OUTDIR" "$RUNDIR/output"

run_one() {
    local cfg="$1"
    local name
    name="$(basename "$cfg" .cfg)"
    # Run from run-scripts so the relative ./output/... stats path resolves.
    ( cd "$RUNDIR" && "$BIN" "$cfg" ) > "$OUTDIR/$name.log" 2>&1
    echo "  ran $name"
}
export -f run_one
export BIN RUNDIR OUTDIR

echo ">> running $(ls "$CFGDIR"/*.cfg | wc -l) baseline configs with $JOBS jobs"
ls "$CFGDIR"/*.cfg | xargs -P "$JOBS" -I{} bash -c 'run_one "$@"' _ {}

echo ">> logs in $OUTDIR"
