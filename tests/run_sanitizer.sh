#!/usr/bin/env bash
# Phase 8 sanitizer smoke test: golden + edge configs under ASan/UBSan.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/third_party/Kangaroo/simulator/bin/asan/cache"

if [ ! -x "$BIN" ]; then
  bash "$ROOT/scripts/build-asan.sh" >/dev/null
fi

run_one() {
  cfg="$1"
  out="$("$BIN" "$cfg" 2>&1)"
  if ! printf '%s\n' "$out" | grep -q '^Processed '; then
    echo "SANITIZER FAIL: no Processed line for $cfg"
    echo "$out" | tail -20
    exit 1
  fi
  if printf '%s\n' "$out" | grep -Eq 'AddressSanitizer|UndefinedBehaviorSanitizer|runtime error|leak'; then
    echo "SANITIZER FAIL: sanitizer diagnostics for $cfg"
    echo "$out" | tail -40
    exit 1
  fi
}

run_one "$ROOT/configs/golden/sa-golden.cfg"

out="$("$BIN" "$ROOT/configs/golden/sa-golden.cfg" 2>&1)"
got="$(printf '%s\n' "$out" | grep '^Miss Rate:' | tail -1)"
want="$(cat "$ROOT/tests/golden.expected")"
if [ "$got" != "$want" ]; then
  echo "SANITIZER GOLDEN MISMATCH: got $got, want $want"
  exit 1
fi

EDGE_BIN="$BIN" bash "$ROOT/tests/run_edge_cases.sh"
echo "phase8: sanitizer PASS"
