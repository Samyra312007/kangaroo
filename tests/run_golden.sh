#!/usr/bin/env bash
# Phase 2 golden-trace regression: run the golden config twice and require
# (a) byte-identical outputs (determinism) and (b) the steady-state miss rate
#     to match the committed expected value.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/third_party/Kangaroo/simulator/bin/cache"
CFG="$ROOT/configs/golden/sa-golden.cfg"
EXP="$ROOT/tests/golden.expected"
OUT1="$(mktemp)"
OUT2="$(mktemp)"
"$BIN" "$CFG" >"$OUT1" 2>&1
"$BIN" "$CFG" >"$OUT2" 2>&1
GOT="$(grep 'Miss Rate:' "$OUT1" | tail -1)"
WANT="$(cat "$EXP")"
if ! cmp -s "$OUT1" "$OUT2"; then
  echo "DETERMINISM FAIL: two identical runs produced different output"
  rm -f "$OUT1" "$OUT2"
  exit 1
fi
if [ "$GOT" != "$WANT" ]; then
  echo "GOLDEN MISMATCH"
  echo " got:  $GOT"
  echo " want: $WANT"
  rm -f "$OUT1" "$OUT2"
  exit 1
fi
echo "phase2: golden + determinism PASS ($GOT)"
rm -f "$OUT1" "$OUT2"
