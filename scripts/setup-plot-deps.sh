#!/usr/bin/env bash
#
# Create a local virtualenv with the plotting dependencies (matplotlib,
# numpy) for scripts/plot-sweeps.py. No root required.
#
# Usage:  scripts/setup-plot-deps.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"

if [ ! -x "$VENV/bin/python" ]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet matplotlib numpy
echo "plot deps ready: $VENV/bin/python"
