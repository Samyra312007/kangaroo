#!/usr/bin/env python3
"""Generate Phase 10 AdaKanga workload configs.

The workload has four phases so the optimal admission, KLog capacity, and KLog
partition settings change over time.  Fixed configurations cannot follow that
change; AdaKanga observes recent misses and write pressure, then retunes its
parameters with bounded hysteresis.
"""

from pathlib import Path
import sys

CONFIG_DIR = Path("configs/phase10")
RESULTS_DIR = Path("results/phase10/logs")

PHASES = [
    (10, 1, 2000, 4096),
    (1, 10000, 20000, 4096),
    (10, 1, 2000, 4096),
]

STATIC_IDS = list(range(1, 10001))
STATIC_REPEATS = 5
STATIC_SIZE = 4096


def requests():
    reqs = []
    for repeat, start, end, size in PHASES:
        ids = list(range(start, end + 1))
        for _ in range(repeat):
            for obj_id in ids:
                reqs.append((obj_id, size))
    return reqs


def static_requests():
    reqs = []
    for _ in range(STATIC_REPEATS):
        for obj_id in STATIC_IDS:
            reqs.append((obj_id, STATIC_SIZE))
    return reqs


def trace_string(reqs):
    return ", ".join(f"{obj_id}, {size}" for obj_id, size in reqs)


def base_config():
    return {
        "cache": "  flashSizeMB = 20;\n  memorySizeMB = 5;\n  slowWarmup = 1;\n",
        "memoryCache": "  policy = \"LRU\";\n",
        "sets": "  setCapacity = 4096;\n  rripBits = 3;\n",
    }


def adaptive_config(path, interval=1000, ceiling=3000000, trace_kind="manual", initial_ratio=0.90, start_log_fraction=0.50, max_admit_hits=4):
    config = base_config()

    config["log"] = "  percentLog = 50.0;\n  readmit = 1;\n"
    config["preLogAdmission"] = f"""  policy = "Adaptive";
  admitRatio = {initial_ratio:.2f};
  minRatio = 0.20;
  maxRatio = 1.00;
  ratioStep = 0.05;
  minAdmitHits = 1;
  maxAdmitHits = {max_admit_hits};
  setThreshold = 1;
  minThreshold = 1;
  maxThreshold = 6;
  startLogFraction = {start_log_fraction:.2f};
  minLogFraction = 0.10;
  maxLogFraction = 1.00;
  logFractionStep = 0.10;
  partitions = 4;
  minPartitions = 1;
  maxPartitions = 64;
  interval = {interval};
  writeCeilingBytes = {ceiling};
  missHysteresis = 0.01;
  plateauIntervals = 2;
  printDecisions = 1;
"""

    config["preSetAdmission"] = "  policy = \"Threshold\";\n  threshold = 1;\n"
    config["stats"] = f'  outputFile = "{RESULTS_DIR}/{path.stem}.out";\n  collectionIntervalPower = 4;\n'

    if trace_kind == "manual":
        config["trace"] = f'  format = "Manual";\n  requestStride = 2;\n  requests = ({trace_string(requests())});\n'
    elif trace_kind == "static":
        config["trace"] = f'  format = "Manual";\n  requestStride = 2;\n  requests = ({trace_string(static_requests())});\n'
    else:
        config["trace"] = '  alpha = 0.9;\n  format = "Zipf";\n  numObjects = 1000000;\n  totalKAccesses = 100;\n'

    path.write_text(render(config))


def fixed_config(path, ratio, percent_log, partitions, ceiling=None, trace_kind="manual"):
    config = base_config()
    config["log"] = f"  percentLog = {percent_log:.1f};\n  readmit = 1;\n  partitions = {partitions};\n"
    config["preLogAdmission"] = f"""  policy = "Random";
  admitRatio = {ratio:.2f};
"""
    config["preSetAdmission"] = "  policy = \"Threshold\";\n  threshold = 1;\n"
    config["stats"] = f'  outputFile = "{RESULTS_DIR}/{path.stem}.out";\n  collectionIntervalPower = 4;\n'

    if trace_kind == "manual":
        config["trace"] = f'  format = "Manual";\n  requestStride = 2;\n  requests = ({trace_string(requests())});\n'
    elif trace_kind == "static":
        config["trace"] = f'  format = "Manual";\n  requestStride = 2;\n  requests = ({trace_string(static_requests())});\n'
    else:
        config["trace"] = '  alpha = 0.9;\n  format = "Zipf";\n  numObjects = 1000;\n  totalKAccesses = 10;\n'

    if ceiling is not None:
        config["preLogAdmission"] += f'  ceilingHint = {ceiling};\n'

    path.write_text(render(config))


def render(config):
    out = []
    for section, body in config.items():
        out.append(f"{section} = {{\n{body}}};\n")
    return "".join(out)


def main():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    shift_fixed = [
        ("fixed_all_p100_log90_partitions4.cfg", 1.00, 90.0, 4, 24000),
        ("fixed_p090_log50_partitions4.cfg", 0.90, 50.0, 4, 24000),
        ("fixed_p050_log10_partitions1.cfg", 0.50, 10.0, 1, 24000),
        ("fixed_p100_log10_partitions4.cfg", 1.00, 10.0, 4, 24000),
    ]

    for name, ratio, percent_log, partitions, ceiling in shift_fixed:
        fixed_config(CONFIG_DIR / name, ratio, percent_log, partitions, ceiling)

    for ratio_pct in (20, 30, 40, 50, 60, 70, 80, 90, 100):
        fixed_config(CONFIG_DIR / f"fixed_p{ratio_pct}.cfg", ratio_pct / 100.0, 50.0, 4)

    for name, ratio in (("static_fixed_all.cfg", 1.00), ("static_fixed_09.cfg", 0.90), ("static_fixed_05.cfg", 0.50)):
        fixed_config(CONFIG_DIR / name, ratio, 50.0, 4, trace_kind="static")

    adaptive_config(CONFIG_DIR / "adaptive.cfg", interval=1000, ceiling=2000000, start_log_fraction=0.50)
    adaptive_config(CONFIG_DIR / "adaptive_static.cfg", interval=1000, ceiling=4000000, trace_kind="static", initial_ratio=1.00, start_log_fraction=1.00, max_admit_hits=1)
    print(f"Generated {len(shift_fixed) + 9 + 3 + 2} Phase 10 configs under {CONFIG_DIR}")


if __name__ == "__main__":
    sys.exit(main())
