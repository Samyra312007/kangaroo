#!/usr/bin/env bash
# Build a sanitizer target at third_party/Kangaroo/simulator/bin/asan/cache.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPS="$ROOT/.deps"
SIM="$ROOT/third_party/Kangaroo/simulator"

if [ ! -x "$DEPS/venv/bin/scons" ]; then
    echo "error: run scripts/setup-deps.sh first" >&2
    exit 1
fi

bash "$ROOT/scripts/build.sh" >/dev/null

ASAN_BUILD=1 \
ASAN_BIN_DIR=bin/asan \
LIBCFG_INCLUDE="$DEPS/libconfig/include" \
LIBCFG_LIB="$DEPS/libconfig/lib" \
    "$DEPS/venv/bin/scons" -C "$SIM"

echo ">> built sanitizer target $SIM/bin/asan/cache"
