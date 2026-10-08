#!/usr/bin/env python3
"""Collect Phase 1 baseline results into a CSV.

Parses each per-config log written by scripts/run-baselines.sh and extracts the
final summary line printed by the simulator:

    Miss Rate: <value> Flash Write Amp: <value>

The last such line in a log is the end-of-run (post-warmup) steady-state result.

Usage:  scripts/collect.py
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGDIR = ROOT / "results" / "baselines" / "logs"
OUTCSV = ROOT / "results" / "baselines" / "baseline_results.csv"

SUMMARY = re.compile(r"Miss Rate:\s*(\S+)\s+Flash Write Amp:\s*(\S+)")
NAME = re.compile(r"memSize(\d+)MB-flashSize(\d+)MB")


def design_of(name: str) -> str:
    if "setCapacity" in name:
        return "SA"  # set-associative baseline (memoryCache + sets)
    if "logPer" in name:
        return "LS"  # log-structured baseline (memoryCache + log)
    return "?"


def parse_log(text: str) -> tuple[float, float] | None:
    last = None
    for match in SUMMARY.finditer(text):
        last = match
    if last is None:
        return None
    try:
        return float(last.group(1)), float(last.group(2))
    except ValueError:
        return None


def main() -> int:
    rows = []
    for log in sorted(LOGDIR.glob("*.log")):
        parsed = parse_log(log.read_text(errors="replace"))
        if parsed is None:
            continue
        miss_rate, write_amp = parsed
        nm = NAME.search(log.stem)
        rows.append(
            {
                "design": design_of(log.stem),
                "flash_mb": int(nm.group(2)) if nm else "",
                "mem_mb": int(nm.group(1)) if nm else "",
                "miss_rate": f"{miss_rate:.6f}",
                "flash_write_amp": f"{write_amp:.4f}",
                "config": log.stem,
            }
        )

    rows.sort(key=lambda r: (str(r["design"]), r["flash_mb"], r["mem_mb"]))
    OUTCSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTCSV.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "design",
                "flash_mb",
                "mem_mb",
                "miss_rate",
                "flash_write_amp",
                "config",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {OUTCSV} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
