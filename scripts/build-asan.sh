#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/third_party/Kangaroo/simulator"
# Rebuild with sanitizers by overriding SCons flags via environment.
CXXFLAGS="-std=c++14 -g -O1 -Wall -fsanitize=address,undefined -fno-omit-frame-pointer" \
LDFLAGS="-fsanitize=address,undefined" \
scons -Q 2>&1 | tail -5
echo "asan build attempted (see errors above if any)"
