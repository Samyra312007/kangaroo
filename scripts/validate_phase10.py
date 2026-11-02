#!/usr/bin/env python3
import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BIN = REPO / "third_party/Kangaroo/simulator/bin/cache"
CONFIG_DIR = REPO / "configs/phase10"
RESULT_DIR = REPO / "results/phase10"
LOG_DIR = RESULT_DIR / "logs"
SUMMARY_PATH = RESULT_DIR / "summary.json"

MISS_RE = re.compile(r"Miss Rate:\s+([0-9]+(?:\.[0-9]+)?)")
WAF_RE = re.compile(r"Flash Write Amp:\s+([0-9]+(?:\.[0-9]+)?)")
FINAL_RE = re.compile(r"AdaKanga final: (.*)")
NUM_RE = re.compile(r'"([A-Za-z0-9_]+)":\s+([0-9]+(?:\.[0-9]+)?)')

def run_config(config_path):
    proc = subprocess.run([str(BIN), str(config_path)], text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"cache failed for {config_path}: {proc.stderr}")

    miss_values = [float(x) for x in MISS_RE.findall(proc.stdout)]
    waf_values = [float(x) for x in WAF_RE.findall(proc.stdout)]
    final_match = FINAL_RE.search(proc.stdout)

    final_stats = {}
    stats_path = LOG_DIR / f"{config_path.stem}.out"
    if stats_path.exists():
        for match in NUM_RE.finditer(stats_path.read_text()):
            final_stats[match.group(1)] = float(match.group(2))

    return {
        "config": config_path.name,
        "finalMissRate": miss_values[-1] if miss_values else None,
        "finalFlashWriteAmp": waf_values[-1] if waf_values else None,
        "finalAdaKanga": final_match.group(1) if final_match else None,
        "finalStats": final_stats,
    }

def main():
    configs = sorted(CONFIG_DIR.glob("*.cfg"))
    results = {run_config(config)["config"]: run_config(config) for config in configs}

    static_fixed = [
        "static_fixed_all.cfg",
        "static_fixed_09.cfg",
        "static_fixed_05.cfg",
    ]
    static_fixed_results = [results[name] for name in static_fixed]
    static_best = min(static_fixed_results, key=lambda item: item["finalMissRate"])
    static_adaptive = results["adaptive_static.cfg"]

    fixed_configs = sorted(
        name for name in results
        if name.startswith("fixed_") and name not in static_fixed
    )
    fixed_results = [results[name] for name in fixed_configs]
    fixed_best = min(fixed_results, key=lambda item: item["finalMissRate"])
    adaptive_shift = results["adaptive.cfg"]

    static_delta = abs(static_adaptive["finalMissRate"] - static_best["finalMissRate"]) / static_best["finalMissRate"]
    shift_strict = adaptive_shift["finalMissRate"] < fixed_best["finalMissRate"]

    ceiling_ok = (
        adaptive_shift["finalStats"].get("maxIntervalWriteBytes", 0)
        <= adaptive_shift["finalStats"].get("writeCeilingBytes", 0)
        and static_adaptive["finalStats"].get("maxIntervalWriteBytes", 0)
        <= static_adaptive["finalStats"].get("writeCeilingBytes", 0)
    )

    summary = {
        "configs": results,
        "workloads": {
            "static": {
                "fixedMissRates": {name: results[name]["finalMissRate"] for name in static_fixed},
                "bestFixedMissRate": static_best["finalMissRate"],
                "bestFixedConfig": static_best["config"],
                "adaptiveMissRate": static_adaptive["finalMissRate"],
                "relativeDelta": static_delta,
                "within2Percent": static_delta <= 0.02,
            },
            "shift": {
                "fixedMissRates": {name: results[name]["finalMissRate"] for name in fixed_configs},
                "bestFixedMissRate": fixed_best["finalMissRate"],
                "bestFixedConfig": fixed_best["config"],
                "adaptiveMissRate": adaptive_shift["finalMissRate"],
                "strictlyLowerThanBestFixed": shift_strict,
            },
        },
        "writeCeiling": {
            "adaptive": adaptive_shift["finalStats"],
            "adaptiveStatic": static_adaptive["finalStats"],
            "maxObservedIntervalBytesWithinCeiling": ceiling_ok,
        },
        "criteria": {
            "adaptiveStaticWithin2Percent": static_delta <= 0.02,
            "adaptiveShiftStrictlyLowerThanBestFixed": shift_strict,
            "writeCeilingEnforcedForAdaptiveRuns": ceiling_ok,
        },
    }

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n")

    print(json.dumps(summary["criteria"], indent=2))
    print(f"Static adaptive: {static_adaptive['finalMissRate']:.6f} "
          f"(best fixed {static_best['finalMissRate']:.6f}, delta {static_delta:.4f})")
    print(f"Shift adaptive: {adaptive_shift['finalMissRate']:.6f} "
          f"(best fixed {fixed_best['finalMissRate']:.6f})")
    print(f"Wrote {SUMMARY_PATH}")

if __name__ == "__main__":
    main()
