#!/usr/bin/env bash
#
# Build the vendored Kangaroo simulator.
#
# Requires scripts/setup-deps.sh to have been run first. Points the build at the
# project-local libconfig++ prefix via LIBCFG_INCLUDE / LIBCFG_LIB, which the
# (patched) SConstruct consumes.
#
# Usage:  scripts/build.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPS="$ROOT/.deps"
SIM="$ROOT/third_party/Kangaroo/simulator"

if [ ! -x "$DEPS/venv/bin/scons" ]; then
    echo "error: run scripts/setup-deps.sh first" >&2
    exit 1
fi

LIBCFG_INCLUDE="$DEPS/libconfig/include" \
LIBCFG_LIB="$DEPS/libconfig/lib" \
    "$DEPS/venv/bin/scons" -C "$SIM"

echo ">> built $SIM/bin/cache"
