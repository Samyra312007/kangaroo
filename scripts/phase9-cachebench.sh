#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHELIB_DIR="${CACHELIB_DIR:-$ROOT/third_party/CacheLib-1}"
CACHELIB_URL="${CACHELIB_URL:-https://github.com/facebookincubator/cachelib.git}"
CACHELAB_URL="${CACHELAB_URL:-https://github.com/facebookincubator/cachelib-cachelab.git}"
BRANCH="${CACHELIB_BRANCH:-main}"
RUN=0
SKIP=1
DEVICE=""

usage() {
  cat <<'USAGE'
phase9-cachebench.sh: CacheLib raw-flash track for Phase 9 / paper section 5.5.

Options:
  --run                  Attempt the CacheLib/cachebench production track.
  --device <path>        Raw flash device or file to use for CacheLab.
  --clone                Clone CacheLib into third_party/CacheLib-1 if absent.
  --branch <branch>      CacheLib branch, default: main.

Without a real flash device, this script intentionally reports the hardware
limitation and exits successfully. The simulator-side comparison is implemented
in scripts/phase9-simulation.sh.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run)
      RUN=1
      SKIP=0
      shift
      ;;
    --device)
      DEVICE="${2:-}"
      if [[ -z "$DEVICE" ]]; then
        echo "--device requires a path" >&2
        exit 1
      fi
      shift 2
      ;;
    --clone)
      if [[ ! -d "$CACHELIB_DIR" ]]; then
        git clone "$CACHELIB_URL" "$CACHELIB_DIR"
      fi
      shift
      ;;
    --branch)
      BRANCH="${2:-}"
      if [[ -z "$BRANCH" ]]; then
        echo "--branch requires a branch name" >&2
        exit 1
      fi
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 1
      ;;
  esac
done

if [[ "$RUN" == "0" || "$SKIP" == "1" || -z "$DEVICE" ]]; then
  echo "phase9 CacheLib track: skipped (no raw flash device supplied)."
  echo "For the simulator-side section 5.5 comparison run:"
  echo "  bash scripts/phase9-simulation.sh"
  echo "To attempt a real CacheLab run, set a raw flash device and pass:"
  echo "  bash scripts/phase9-cachebench.sh --run --device /dev/nvme0n1 --clone"
  exit 0
fi

if [[ ! -d "$CACHELIB_DIR" ]]; then
  echo "phase9 CacheLib track: skipped because $CACHELIB_DIR is not present." >&2
  echo "Clone it first with: --clone" >&2
  exit 1
fi

if ! [[ -e "$DEVICE" ]]; then
  echo "phase9 CacheLib track: skipped because device path does not exist: $DEVICE" >&2
  exit 1
fi

if ! command -v cachebench >/dev/null 2>&1; then
  echo "phase9 CacheLib track: skipped because cachebench is not installed or not on PATH." >&2
  echo "Build CacheLib/Cachelab first; see docs/phase9.md for instructions." >&2
  exit 1
fi

echo "CacheLib branch: $BRANCH"
echo "Raw flash device: $DEVICE"
echo "CacheLab command template:"
echo "  cachebench -f cachelab_configs/kangaroo.json -d $DEVICE"
echo "  cachebench -f cachelab_configs/sa.json -d $DEVICE"
echo "  cachebench -f cachelab_configs/ls.json -d $DEVICE"
echo "Replace cachelab_configs/*.json with CacheLab configs that reproduce section 5.5."
echo "This wrapper intentionally does not fabricate CacheLab results when hardware is absent."
