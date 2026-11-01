#!/usr/bin/env bash
#
# Phase 7: run every sweep configuration from configs/sweeps/ in parallel
# and capture stdout to results/sweeps/logs/<name>.log. Stats JSON files are
# written by the simulator to results/sweeps/json/ (absolute paths baked
# into the configs).
#
# Usage:  scripts/run-sweeps.sh [JOBS]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT/third_party/Kangaroo/simulator/bin/cache"
CFGDIR="$ROOT/configs/sweeps"
LOGDIR="$ROOT/results/sweeps/logs"
JOBS="${1:-12}"

if [ ! -x "$BIN" ]; then
    echo "error: $BIN not found; run scripts/build.sh first" >&2
    exit 1
fi

if ! ls "$CFGDIR"/*.cfg >/dev/null 2>&1; then
    echo "error: no configs in $CFGDIR; run scripts/gen-sweep-configs.py first" >&2
    exit 1
fi

mkdir -p "$LOGDIR"

run_one() {
    local cfg="$1"
    local name
    name="$(basename "$cfg" .cfg)"
    # Resume support: only skip runs that finished cleanly ('Processed' is
    # the simulator's last line). Killed/partial runs are re-executed.
    if [ "${FORCE:-0}" != "1" ] \
        && grep -q "Processed" "$LOGDIR/$name.log" 2>/dev/null \
        && [ -s "$ROOT/results/sweeps/json/$name.out" ]; then
        echo "  skip $name (already ran)"
        return 0
    fi
    if ( cd "$ROOT" && "$BIN" "$cfg" ) > "$LOGDIR/$name.log" 2>&1; then
        echo "  ok   $name"
    else
        echo "  FAIL $name" >&2
        return 1
    fi
}
export -f run_one
export BIN ROOT LOGDIR

echo ">> running $(ls "$CFGDIR"/*.cfg | wc -l) sweep configs with $JOBS jobs"
ls "$CFGDIR"/*.cfg | xargs -P "$JOBS" -I{} bash -c 'run_one "$@"' _ {}

echo ">> logs in $LOGDIR"
