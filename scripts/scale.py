#!/usr/bin/env python3
"""Appendix B scaling methodology (paper Table 4) for the Phase 7 evaluation.

The SOSP '21 paper scales sampled traces to full-server equivalents
(Appendix B, Table 4) so experiments run on a sample can be mapped back to
production-scale numbers. This module implements the two scaling modes used
by our Phase 7 sweeps:

1. Object-size scaling at constant working set (Fig. 11):
     - object sizes are multiplied by S (simulator `trace.objectScaling`),
     - the object count is divided by S so the working set in bytes is fixed,
     - the KLog DRAM index ratio (`cache.memOverheadRatio`) is divided by S so
       index bits per object stay constant, mirroring the artifact's
       `log_dram_ratio` adjustment (run-scripts/genConfigs.py).

2. Request-sample scaling (Table 4):
     - a 1/f request sample is mapped back to the full server by multiplying
       the request rate by 1/f while wall-clock duration is preserved.

Run as a script to emit results/sweeps/table4_scaling.csv:

    python3 scripts/scale.py
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Simulator defaults (third_party/Kangaroo/simulator/constants.hpp and the
# Zipf generator: every object is BASE_OBJ_BYTES and `trace.numObjects` is
# interpreted in thousands).
BASE_OBJ_BYTES = 64
BASE_NUM_OBJECTS_K = 1000
INDEX_LOG_RATIO = 0.02  # cache.memOverheadRatio default (index bytes / log bytes)

# Paper FB-trace constants used for request-sample scaling
# (third_party/Kangaroo/graph-scripts/util.py + parameters.py):
FB_SAMPLED_ACCESSES = 173_691_960
FB_WINDOW_S = 21 * 24 * 3600
FB_SAMPLE_FACTOR = 600

MIB = 1024 * 1024


def full_server_request_rate(sample_fraction: float = 1.0) -> float:
    """Full-server request rate implied by a 1/f request sample."""
    sampled_rate = FB_SAMPLED_ACCESSES / FB_WINDOW_S
    return sampled_rate / sample_fraction


def object_size_sweep_params(scale: float) -> dict:
    """Config parameters for a constant-working-set object-size point (Fig. 11)."""
    if scale <= 0:
        raise ValueError("scale must be > 0")
    num_objects_k = max(1, round(BASE_NUM_OBJECTS_K / scale))
    return {
        "object_scaling": float(scale),
        "num_objects_k": num_objects_k,
        "num_objects": num_objects_k * 1000,
        "avg_obj_bytes": BASE_OBJ_BYTES * scale,
        "working_set_mb": (num_objects_k * 1000 * BASE_OBJ_BYTES * scale) / MIB,
        # Keep index bits per KLog object constant as object size changes.
        "mem_overhead_ratio": INDEX_LOG_RATIO / scale,
    }


def main() -> int:
    out = ROOT / "results" / "sweeps" / "table4_scaling.csv"
    out.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []

    # Mode 1: object-size sweep at constant working set (Fig. 11).
    for scale in (0.5, 1.0, 2.0, 4.0):
        p = object_size_sweep_params(scale)
        rows.append(
            {
                "mode": "object_size",
                "scale_factor": f"{scale:g}",
                "avg_obj_bytes": f"{p['avg_obj_bytes']:g}",
                "num_objects": p["num_objects"],
                "working_set_mb": f"{p['working_set_mb']:.2f}",
                "request_rate_rps": "",
                "flash_mb": 20,
                "dram_mb": 5,
                "mem_overhead_ratio": f"{p['mem_overhead_ratio']:.6f}",
                "notes": "constant working set; numObjects /= S, sizes *= S",
            }
        )

    # Mode 2: request-sample -> full-server mapping (Table 4).
    for fraction in (1.0, 100.0, 600.0):
        rows.append(
            {
                "mode": "request_sample",
                "scale_factor": f"{fraction:g}",
                "avg_obj_bytes": BASE_OBJ_BYTES,
                "num_objects": BASE_NUM_OBJECTS_K * 1000,
                "working_set_mb": f"{(BASE_NUM_OBJECTS_K * 1000 * BASE_OBJ_BYTES) / MIB:.2f}",
                "request_rate_rps": f"{full_server_request_rate(fraction):.1f}",
                "flash_mb": 20,
                "dram_mb": 5,
                "mem_overhead_ratio": f"{INDEX_LOG_RATIO:.6f}",
                "notes": "1/f request sample; rate *= 1/f, duration preserved",
            }
        )

    fields = [
        "mode",
        "scale_factor",
        "avg_obj_bytes",
        "num_objects",
        "working_set_mb",
        "request_rate_rps",
        "flash_mb",
        "dram_mb",
        "mem_overhead_ratio",
        "notes",
    ]
    with out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {out} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
