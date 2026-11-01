#!/usr/bin/env python3
"""Collect Phase 7 sweep results into per-figure CSVs.

Reads configs/sweeps/manifest.json, the per-run logs written by
scripts/run-sweeps.sh, and the stats JSON files the simulator wrote to
results/sweeps/json/, then emits:

  results/sweeps/fig07_timeseries.csv       windowed miss ratio over time
  results/sweeps/fig08_pareto.csv           miss ratio vs device write rate
  results/sweeps/fig09_dram_sweep.csv       DRAM sweep
  results/sweeps/fig10_flash_sweep.csv      flash capacity sweep
  results/sweeps/fig11_objsize_sweep.csv    object-size sweep (constant WS)
  results/sweeps/fig12a_admission_prob.csv  pre-flash admission probability
  results/sweeps/fig12b_rrip_bits.csv       FIFO vs RRIParoo bits
  results/sweeps/fig12c_log_size.csv        KLog size % of flash
  results/sweeps/fig12d_threshold.csv       KSet admission threshold
  results/sweeps/table1_dram_bits.csv       DRAM bits/object (paper Table 1)
  results/sweeps/all_runs.csv               every run's full metrics

Device write rate follows the artifact's methodology
(third_party/Kangaroo/graph-scripts/{parameters,util}.py): application
flash writes are converted to device MB/s through the best-fit device
write-amplification curve, evaluated at the run's flash utilization. The
synthetic trace is mapped onto the paper's evaluation window by assuming
it runs at the full-server request rate implied by the sampled Facebook
trace (173.7 M sampled accesses / 21 days, 1/600 sampling).

Usage:  python3 scripts/collect-sweeps.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "configs" / "sweeps" / "manifest.json"
LOGDIR = ROOT / "results" / "sweeps" / "logs"
JSONDIR = ROOT / "results" / "sweeps" / "json"
OUTDIR = ROOT / "results" / "sweeps"

MIB = 1024 * 1024

# Device write-amplification curve vs. flash utilization, from the paper's
# Fig. 2 (ported from graph-scripts/parameters.py).
DEV_WA = [
    (0.0, 0.0),
    (0.25, 1.143322),
    (0.50, 1.238678),
    (0.66, 1.593991),
    (0.80, 2.087966),
    (0.90, 3.382906),
    (0.99, 9.551039),
    (float("inf"), 9.551039),
]

# Full-server request rate implied by the paper's sampled FB trace
# (graph-scripts/util.py: 173,691,960 accesses over 21 days, 1/600 sample).
FB_SAMPLED_ACCESSES = 173_691_960
FB_WINDOW_S = 21 * 24 * 3600
FB_SAMPLE_FACTOR = 600
FULL_SERVER_RATE = FB_SAMPLED_ACCESSES * FB_SAMPLE_FACTOR / FB_WINDOW_S

SUMMARY_LINE = re.compile(r"Miss Rate:\s*(\S+)\s+Flash Write Amp:\s*(\S+)")

# Paper Table 1 overall DRAM contributions (b/object) for the 2 TB / 200 B
# parameterization; KLog's 48 b/obj applies to the ~5% of objects in KLog.
PAPER_TABLE1 = {
    "klog_index": 2.4,       # 48 b per KLog object x 5% of objects
    "kset_bloom_rrip": 4.0,  # Bloom + RRIParoo hit bit
    "total": 7.0,
}


def dev_write_rate(app_mbps: float, flash_frac: float) -> float:
    """Device MB/s = device WA(flash utilization) x application MB/s."""
    ind = 0
    for i, (frac, _wa) in enumerate(DEV_WA):
        if flash_frac < frac:
            ind = i - 1
            break
    else:
        ind = len(DEV_WA) - 2
    if ind < 0:
        ind = 0
    if ind + 1 >= len(DEV_WA):
        slope = 0.0
    else:
        x0, y0 = DEV_WA[ind]
        x1, y1 = DEV_WA[ind + 1]
        slope = (y1 - y0) / (x1 - x0)
    wa = DEV_WA[ind][1] + slope * (flash_frac - DEV_WA[ind][0])
    return wa * app_mbps


def load_blobs(path: Path) -> list[dict]:
    """Parse the simulator's concatenated JSON stats dumps."""
    text = path.read_text(errors="replace")
    decoder = json.JSONDecoder()
    idx = 0
    blobs: list[dict] = []
    while True:
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        obj, offset = decoder.raw_decode(text, idx)
        blobs.append(obj)
        idx = offset
    return blobs


def parse_log(path: Path) -> dict:
    """Last 'Miss Rate / Flash Write Amp' line = end-of-run summary."""
    last = None
    for match in SUMMARY_LINE.finditer(path.read_text(errors="replace")):
        last = match
    if last is None:
        raise ValueError(f"no summary line in {path}")
    return {"log_miss_rate": float(last.group(1)), "log_waf": float(last.group(2))}


def admitted_ratio(blob: dict, which: str) -> float | None:
    """Achieved admission ratio (numAdmits / numPossibleAdmits)."""
    for key, stats in blob.items():
        if which in key and "numAdmits" in stats:
            possible = stats.get("numPossibleAdmits", 0)
            if possible:
                return stats["numAdmits"] / possible
    return None


def flash_utilization(blob: dict) -> float:
    current = 0
    capacity = 0
    if "sets" in blob and "current_size" in blob["sets"]:
        current += blob["sets"]["current_size"]
        capacity += blob["sets"]["numSets"] * blob["sets"]["setCapacity"]
    if "log" in blob and "current_size" in blob["log"]:
        current += blob["log"]["current_size"]
        capacity += blob["log"]["logCapacity"]
    return current / capacity if capacity else 0.0


def bytes_written(blob: dict) -> int:
    total = 0
    for section in ("sets", "log"):
        if section in blob:
            total += blob[section].get("bytes_written", 0)
    return total


def run_metrics(name: str, entry: dict) -> dict:
    log_path = LOGDIR / f"{name}.log"
    json_path = JSONDIR / f"{name}.out"
    if not log_path.exists():
        raise FileNotFoundError(f"missing log for {name}: {log_path}")
    if not json_path.exists():
        raise FileNotFoundError(f"missing stats for {name}: {json_path}")

    params = entry["params"]
    log = parse_log(log_path)
    blobs = load_blobs(json_path)
    blob = blobs[-1]
    g = blob["global"]

    total = g.get("totalAccesses", 0)
    misses = g.get("misses", 0)
    miss_rate = misses / total if total else 0.0

    writes = bytes_written(blob)
    duration_s = total / FULL_SERVER_RATE if total else 0.0
    app_mbps = (writes / MIB) / duration_s if duration_s else 0.0
    frac = flash_utilization(blob)
    dev_mbps = dev_write_rate(app_mbps, frac)

    lru_capacity = blob.get("memCache", {}).get("lruCacheCapacity", 0)
    dram_overhead = params["mem_mb"] * MIB - lru_capacity
    num_objects = params["num_objects_k"] * 1000
    dram_bits = dram_overhead * 8 / num_objects if num_objects else 0.0

    return {
        "config": name,
        "design": entry["design"],
        "mem_mb": params["mem_mb"],
        "flash_mb": params["flash_mb"],
        "miss_rate": miss_rate,
        "waf": log["log_waf"],
        "bytes_written": writes,
        "duration_s": round(duration_s, 2),
        "app_write_mbps": app_mbps,
        "dev_write_mbps": dev_mbps,
        "flash_frac": frac,
        "dram_overhead_bytes": dram_overhead,
        "dram_bits_per_object": dram_bits,
        "admit_ratio_prelog": admitted_ratio(blob, "preLogAdmission"),
        "admit_ratio_preset": admitted_ratio(blob, "preSetAdmission"),
        "total_accesses": total,
    }


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path} ({len(rows)} rows)")


def fig07_timeseries(manifest: dict) -> None:
    rows: list[dict] = []
    total_requests = manifest["base"]["total_requests"]
    for point in manifest["sweeps"]["fig07"]:
        name = point["config"]
        design = point["design"]
        blobs = load_blobs(JSONDIR / f"{name}.out")
        prev = None
        for i, blob in enumerate(blobs):
            g = blob.get("global", {})
            accesses = g.get("totalAccesses", 0)
            misses = g.get("misses", 0)
            if prev is not None:
                d_access = accesses - prev[0]
                if d_access > 0:
                    d_miss = misses - prev[1]
                    rows.append(
                        {
                            "design": design,
                            "dump": i,
                            "accesses": accesses,
                            "day": round(7.0 * accesses / total_requests, 4),
                            "window_miss_rate": round(d_miss / d_access, 6),
                            "cumulative_miss_rate": round(misses / accesses, 6)
                            if accesses
                            else 0.0,
                        }
                    )
            prev = (accesses, misses)
    write_csv(
        OUTDIR / "fig07_timeseries.csv",
        rows,
        ["design", "dump", "accesses", "day", "window_miss_rate", "cumulative_miss_rate"],
    )


def table1_dram_bits(manifest: dict, metrics: dict) -> None:
    rows: list[dict] = []
    for name, entry in sorted(manifest["configs"].items()):
        design = entry["design"]
        params = entry["params"]
        m = metrics[name]
        overhead = m["dram_overhead_bytes"]
        if overhead < 0:
            raise ValueError(f"{name}: DRAM overhead negative ({overhead})")
        num_objects = params["num_objects_k"] * 1000

        components: list[tuple[str, float, float | None]] = []
        if design == "KANGAROO":
            # Mirror mem_log_sets_cache.cpp capacity split.
            flash_bytes = params["flash_mb"] * MIB
            exact_set = flash_bytes * (1 - params["percent_log"] / 100.0)
            actual_set = exact_set - (exact_set % params["set_capacity"])
            log_capacity = flash_bytes - actual_set
            ratio = params["mem_overhead_ratio"]
            if ratio is None:
                ratio = 0.02
            log_index = log_capacity * ratio
            kset = overhead - log_index
            components = [
                ("klog_index", log_index, PAPER_TABLE1["klog_index"]),
                ("kset_bloom_rrip", kset, PAPER_TABLE1["kset_bloom_rrip"]),
                ("total", overhead, PAPER_TABLE1["total"]),
            ]
        elif design == "LS":
            components = [
                ("klog_index", overhead, 48.0),  # all objects live in the log
                ("total", overhead, 48.0),
            ]
        else:  # SA: per-set Bloom only, no paper reference column
            components = [
                ("kset_bloom", overhead, None),
                ("total", overhead, None),
            ]

        for component, byte_count, paper in components:
            rows.append(
                {
                    "config": name,
                    "design": design,
                    "component": component,
                    "bytes": int(byte_count),
                    "bits_per_object": round(byte_count * 8 / num_objects, 4),
                    "paper_overall_bits": "" if paper is None else paper,
                }
            )
    write_csv(
        OUTDIR / "table1_dram_bits.csv",
        rows,
        ["config", "design", "component", "bytes", "bits_per_object", "paper_overall_bits"],
    )


def main() -> int:
    if not MANIFEST.exists():
        print("error: run scripts/gen-sweep-configs.py first", file=sys.stderr)
        return 1
    manifest = json.loads(MANIFEST.read_text())

    metrics: dict[str, dict] = {}
    errors: list[str] = []
    for name, entry in manifest["configs"].items():
        try:
            metrics[name] = run_metrics(name, entry)
        except (FileNotFoundError, ValueError, KeyError) as exc:
            errors.append(str(exc))

    if errors:
        for message in errors:
            print(f"error: {message}", file=sys.stderr)
        print(f"{len(errors)} run(s) missing; run scripts/run-sweeps.sh", file=sys.stderr)
        return 1

    OUTDIR.mkdir(parents=True, exist_ok=True)

    def pick(point: dict, *keys: str) -> dict:
        m = dict(metrics[point["config"]])
        for key in keys:
            if key in point:
                m[key] = point[key]
        return m

    def row(m: dict, *cols: str) -> dict:
        out = {}
        for col in cols:
            value = m.get(col)
            if isinstance(value, float):
                value = round(value, 6)
            out[col] = value
        return out

    # Fig. 7: windowed miss-ratio time series.
    fig07_timeseries(manifest)

    # Fig. 8: Pareto (miss ratio vs device write rate).
    rows = [
        row(
            pick(p, "design", "mem_mb", "flash_mb"),
            "design", "mem_mb", "flash_mb", "miss_rate", "waf",
            "app_write_mbps", "dev_write_mbps", "flash_frac",
        )
        for p in manifest["sweeps"]["fig08"]
    ]
    write_csv(
        OUTDIR / "fig08_pareto.csv",
        rows,
        ["design", "mem_mb", "flash_mb", "miss_rate", "waf",
         "app_write_mbps", "dev_write_mbps", "flash_frac"],
    )

    # Fig. 9: DRAM sweep.
    rows = [
        row(pick(p, "design", "mem_mb"), "design", "mem_mb", "miss_rate", "waf")
        for p in manifest["sweeps"]["fig09"]
    ]
    write_csv(
        OUTDIR / "fig09_dram_sweep.csv",
        rows,
        ["design", "mem_mb", "miss_rate", "waf"],
    )

    # Fig. 10: flash capacity sweep.
    rows = [
        row(pick(p, "design", "flash_mb"), "design", "flash_mb", "miss_rate", "waf")
        for p in manifest["sweeps"]["fig10"]
    ]
    write_csv(
        OUTDIR / "fig10_flash_sweep.csv",
        rows,
        ["design", "flash_mb", "miss_rate", "waf"],
    )

    # Fig. 11: object-size sweep at constant working set.
    rows = [
        row(
            pick(p, "design", "scale", "object_bytes", "num_objects"),
            "design", "scale", "object_bytes", "num_objects", "miss_rate", "waf",
        )
        for p in manifest["sweeps"]["fig11"]
    ]
    write_csv(
        OUTDIR / "fig11_objsize_sweep.csv",
        rows,
        ["design", "scale", "object_bytes", "num_objects", "miss_rate", "waf"],
    )

    # Fig. 12a: pre-flash admission probability.
    rows = []
    for p in manifest["sweeps"]["fig12a"]:
        m = pick(p, "admit_ratio")
        rows.append(
            {
                "admit_ratio": p["admit_ratio"],
                "achieved_ratio": round(m["admit_ratio_prelog"], 4)
                if m["admit_ratio_prelog"] is not None
                else "",
                "miss_rate": round(m["miss_rate"], 6),
                "waf": round(m["waf"], 4),
                "app_write_mbps": round(m["app_write_mbps"], 4),
                "dev_write_mbps": round(m["dev_write_mbps"], 4),
            }
        )
    write_csv(
        OUTDIR / "fig12a_admission_prob.csv",
        rows,
        ["admit_ratio", "achieved_ratio", "miss_rate", "waf",
         "app_write_mbps", "dev_write_mbps"],
    )

    # Fig. 12b: FIFO vs RRIParoo bits.
    rows = []
    for p in manifest["sweeps"]["fig12b"]:
        m = pick(p, "variant", "bits")
        rows.append(
            {
                "variant": p["variant"],
                "bits": p["bits"],
                "miss_rate": round(m["miss_rate"], 6),
                "waf": round(m["waf"], 4),
            }
        )
    write_csv(
        OUTDIR / "fig12b_rrip_bits.csv",
        rows,
        ["variant", "bits", "miss_rate", "waf"],
    )

    # Fig. 12c: KLog size % of flash (0% = SA).
    rows = []
    for p in manifest["sweeps"]["fig12c"]:
        m = pick(p, "percent_log", "design")
        rows.append(
            {
                "percent_log": p["percent_log"],
                "design": p["design"],
                "miss_rate": round(m["miss_rate"], 6),
                "waf": round(m["waf"], 4),
            }
        )
    write_csv(
        OUTDIR / "fig12c_log_size.csv",
        rows,
        ["percent_log", "design", "miss_rate", "waf"],
    )

    # Fig. 12d: KSet admission threshold.
    rows = []
    for p in manifest["sweeps"]["fig12d"]:
        m = pick(p, "threshold")
        rows.append(
            {
                "threshold": p["threshold"],
                "achieved_ratio": round(m["admit_ratio_preset"], 4)
                if m["admit_ratio_preset"] is not None
                else "",
                "miss_rate": round(m["miss_rate"], 6),
                "waf": round(m["waf"], 4),
            }
        )
    write_csv(
        OUTDIR / "fig12d_threshold.csv",
        rows,
        ["threshold", "achieved_ratio", "miss_rate", "waf"],
    )

    # Table 1: DRAM bits/object from the implementation's own accounting.
    table1_dram_bits(manifest, metrics)

    # Master table: every run.
    rows = [
        {
            "config": name,
            "design": m["design"],
            "mem_mb": m["mem_mb"],
            "flash_mb": m["flash_mb"],
            "miss_rate": round(m["miss_rate"], 6),
            "waf": round(m["waf"], 4),
            "bytes_written": m["bytes_written"],
            "app_write_mbps": round(m["app_write_mbps"], 4),
            "dev_write_mbps": round(m["dev_write_mbps"], 4),
            "flash_frac": round(m["flash_frac"], 4),
            "dram_overhead_bytes": m["dram_overhead_bytes"],
            "dram_bits_per_object": round(m["dram_bits_per_object"], 4),
        }
        for name, m in sorted(metrics.items())
    ]
    write_csv(
        OUTDIR / "all_runs.csv",
        rows,
        ["config", "design", "mem_mb", "flash_mb", "miss_rate", "waf",
         "bytes_written", "app_write_mbps", "dev_write_mbps", "flash_frac",
         "dram_overhead_bytes", "dram_bits_per_object"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
