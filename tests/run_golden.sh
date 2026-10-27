#!/usr/bin/env bash
# Golden-trace regression test: run the golden SA config and check the
# steady-state summary line against the committed expected value.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/third_party/Kangaroo/simulator/bin/cache"
CFG="$ROOT/configs/golden/sa-golden.cfg"
EXP="$ROOT/tests/golden.expected"
OUT="$(mktemp)"
"$BIN" "$CFG" >"$OUT" 2>&1
GOT="$(grep 'Miss Rate:' "$OUT" | tail -1)"
WANT="$(cat "$EXP")"
if [ "$GOT" != "$WANT" ]; then
  echo "GOLDEN MISMATCH"
  echo " got:  $GOT"
  echo " want: $WANT"
  rm -f "$OUT"
  exit 1
fi
echo "golden: PASS ($GOT)"
rm -f "$OUT"
