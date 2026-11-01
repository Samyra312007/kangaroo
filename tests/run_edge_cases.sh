#!/usr/bin/env bash
# Phase 8 edge-case integration tests for exact manual traces.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="${EDGE_BIN:-$ROOT/third_party/Kangaroo/simulator/bin/cache}"

declare -A EXPECTED=(
  [empty]=0
  [all_miss]=1
  [all_hit]=0.1
  [zero_byte]=1
  [threshold_one]=0.1
  [single_segment_log]=1
  [over_capacity]=1
  [duplicate_keys]=0.1
)

for cfg in "$ROOT"/tests/configs/edge/*.cfg; do
  name="$(basename "$cfg" .cfg)"
  want="${EXPECTED[$name]}"
  out="$("$BIN" "$cfg" 2>&1)"
  got="$(printf '%s\n' "$out" | sed -n 's/^Miss Rate: \([0-9.]*\) Flash Write Amp.*/\1/p' | tail -1)"
  if ! printf '%s\n' "$out" | grep -q '^Processed '; then
    echo "EDGE FAIL $name: no Processed line"
    echo "$out" | tail -5
    exit 1
  fi
  if [ "$got" != "$want" ]; then
    echo "EDGE FAIL $name: got $got, want $want"
    exit 1
  fi
  echo "edge $name: PASS ($got)"
done

echo "phase8: edge cases PASS"
