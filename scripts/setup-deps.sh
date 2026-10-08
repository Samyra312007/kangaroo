#!/usr/bin/env bash
#
# Phase 0 dependency bootstrap.
#
# The system packages (scons, libconfig++-dev) normally require root, so this
# script builds both into a project-local prefix under .deps/ instead:
#   * SCons  -> .deps/venv            (Python virtualenv)
#   * libconfig++ -> .deps/libconfig  (built from source)
#
# Usage:  scripts/setup-deps.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPS="$ROOT/.deps"
LIBCFG_VERSION="1.7.3"
LIBCFG_URL="https://github.com/hyperrealm/libconfig/releases/download/v${LIBCFG_VERSION}/libconfig-${LIBCFG_VERSION}.tar.gz"

mkdir -p "$DEPS"

echo ">> dependencies prefix: $DEPS"

# --- SCons (build tool) -----------------------------------------------------
if [ ! -x "$DEPS/venv/bin/scons" ]; then
    echo ">> creating virtualenv and installing SCons"
    python3 -m venv "$DEPS/venv"
    "$DEPS/venv/bin/pip" -q install --upgrade pip
    "$DEPS/venv/bin/pip" -q install scons
else
    echo ">> SCons already installed"
fi

# --- libconfig++ (simulator dependency) -------------------------------------
if [ ! -f "$DEPS/libconfig/lib/libconfig++.so" ]; then
    echo ">> downloading and building libconfig ${LIBCFG_VERSION}"
    curl -sL --max-time 300 -o "$DEPS/libconfig.tar.gz" "$LIBCFG_URL"
    tar -xzf "$DEPS/libconfig.tar.gz" -C "$DEPS"
    (
        cd "$DEPS/libconfig-${LIBCFG_VERSION}"
        ./configure --prefix="$DEPS/libconfig" --disable-examples >/dev/null
        make -j"$(nproc)" >/dev/null
        make install >/dev/null
    )
else
    echo ">> libconfig++ already built"
fi

echo ">> dependencies ready: $DEPS"
