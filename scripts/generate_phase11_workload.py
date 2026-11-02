#!/usr/bin/env python3
"""Generate Phase 11 Kangaroo-TTL workload configs.

The Phase 11 workload mixes short-TTL churn with long-lived objects so that the
simulator can prove four things:

1. Expired objects do not count as hits.
2. KLog flushing drops expired records instead of rewriting them to flash.
3. Short-TTL objects are rejected before flash admission.
4. Long-lived behavior does not regress.
"""

from pathlib import Path
import sys

CONFIG_DIR = Path("configs/phase11")
RESULTS_DIR = Path("results/phase11/logs")

SHORT_SIZE = 8192
LONG_SIZE = 8192
SHORT_IDS = list(range(1, 1001))
LONG_IDS = list(range(10000, 10201))
SHORT_REPEATS = 10
LONG_REPEATS = 10
SHORT_TTL = 1000
SHORT_EXPIRE = 1000
LONG_TTL = 200000


def mixed_requests():
    reqs = []
    t = 0

    for _ in range(SHORT_REPEATS):
        for obj_id in SHORT_IDS:
            t += 1
            expire_time = obj_id + SHORT_EXPIRE - 1
            reqs.append((obj_id, SHORT_SIZE, 0, expire_time))

    for _ in range(LONG_REPEATS):
        for obj_id in LONG_IDS:
            t += 1
            reqs.append((obj_id, LONG_SIZE, 0, 0))

    return reqs


def vanilla_requests():
    reqs = []
    t = 0

    for _ in range(SHORT_REPEATS):
        for obj_id in SHORT_IDS:
            t += 1
            reqs.append((obj_id, SHORT_SIZE, 0, 0))

    for _ in range(LONG_REPEATS):
        for obj_id in LONG_IDS:
            t += 1
            reqs.append((obj_id, LONG_SIZE, 0, 0))

    return reqs


def long_only_requests():
    reqs = []
    t = 0

    for _ in range(LONG_REPEATS):
        for obj_id in LONG_IDS:
            t += 1
            reqs.append((obj_id, LONG_SIZE, 0, 0))

    return reqs


def long_ttl_only_requests():
    reqs = []
    t = 0

    for _ in range(LONG_REPEATS):
        for obj_id in LONG_IDS:
            t += 1
            reqs.append((obj_id, LONG_SIZE, 0, t + LONG_TTL))

    return reqs


def trace_string(reqs):
    return ", ".join(
        f"{obj_id}, {size}, {oracle}, {expire}"
        for obj_id, size, oracle, expire in reqs
    )


def base_config():
    return {
        "cache": "  flashSizeMB = 20;\n  memorySizeMB = 5;\n  slowWarmup = 1;\n",
        "memoryCache": "  policy = \"LRU\";\n",
        "sets": "  setCapacity = 4096;\n  rripBits = 3;\n",
    }


def render(config):
    out = []
    for section, body in config.items():
        out.append(f"{section} = {{\n{body}}};\n")
    return "".join(out)


def vanilla_config(path, reqs):
    config = base_config()
    config["log"] = "  percentLog = 50.0;\n  readmit = 1;\n  partitions = 4;\n"
    config["preLogAdmission"] = """  policy = "Random";
  admitRatio = 0.90;
"""
    config["preSetAdmission"] = "  policy = \"Threshold\";\n  threshold = 1;\n"
    config["stats"] = f'  outputFile = "{RESULTS_DIR}/{path.stem}.out";\n  collectionIntervalPower = 4;\n'
    config["trace"] = f'  format = "Manual";\n  requestStride = 4;\n  requests = ({trace_string(reqs)});\n'
    path.write_text(render(config))


def adaptive_config(
    path,
    reqs,
    short_ttl,
    *,
    interval=1000,
    start_log_fraction=0.50,
    min_log_fraction=0.10,
    max_log_fraction=1.00,
    log_fraction_step=0.10,
    min_ratio=0.20,
    max_ratio=1.00,
    ratio_step=0.05,
    min_threshold=1,
    max_threshold=6,
    write_ceiling_bytes=3000000,
    print_decisions=1,
):
    config = base_config()
    config["log"] = "  percentLog = 50.0;\n  readmit = 1;\n  partitions = 4;\n"
    config["preLogAdmission"] = f"""  policy = "Adaptive";
  admitRatio = 0.90;
  minRatio = {min_ratio};
  maxRatio = {max_ratio};
  ratioStep = {ratio_step};
  minAdmitHits = 1;
  maxAdmitHits = 4;
  setThreshold = 1;
  minThreshold = {min_threshold};
  maxThreshold = {max_threshold};
  startLogFraction = {start_log_fraction};
  minLogFraction = {min_log_fraction};
  maxLogFraction = {max_log_fraction};
  logFractionStep = {log_fraction_step};
  partitions = 4;
  minPartitions = 1;
  maxPartitions = 64;
  interval = {interval};
  writeCeilingBytes = {write_ceiling_bytes};
  missHysteresis = 0.01;
  plateauIntervals = 2;
  shortTtl = {short_ttl};
  printDecisions = {print_decisions};
"""
    config["preSetAdmission"] = "  policy = \"Threshold\";\n  threshold = 1;\n"
    config["stats"] = f'  outputFile = "{RESULTS_DIR}/{path.stem}.out";\n  collectionIntervalPower = 4;\n'
    config["trace"] = f'  format = "Manual";\n  requestStride = 4;\n  requests = ({trace_string(reqs)});\n'
    path.write_text(render(config))


def main():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    mixed = mixed_requests()
    vanilla = vanilla_requests()
    long_only = long_only_requests()
    long_ttl_only = long_ttl_only_requests()

    vanilla_config(CONFIG_DIR / "vanilla.cfg", vanilla)
    adaptive_config(CONFIG_DIR / "ttl_no_short.cfg", mixed, short_ttl=0)
    adaptive_config(CONFIG_DIR / "ttl.cfg", mixed, short_ttl=SHORT_TTL)

    stable = dict(
        interval=10000,
        start_log_fraction=1.00,
        min_log_fraction=1.00,
        max_log_fraction=1.00,
        log_fraction_step=0.10,
        min_ratio=0.90,
        max_ratio=0.90,
        ratio_step=0.05,
        min_threshold=1,
        max_threshold=1,
        write_ceiling_bytes=20000000,
        print_decisions=0,
    )

    vanilla_config(CONFIG_DIR / "long_only_vanilla.cfg", long_only)
    adaptive_config(CONFIG_DIR / "long_only_ttl.cfg", long_only, short_ttl=SHORT_TTL, **stable)
    adaptive_config(CONFIG_DIR / "long_ttl_ttl.cfg", long_ttl_only, short_ttl=SHORT_TTL, **stable)
    vanilla_config(CONFIG_DIR / "long_ttl_vanilla.cfg", long_ttl_only)

    print(f"Generated {len(list(CONFIG_DIR.glob('*.cfg')))} Phase 11 configs under {CONFIG_DIR}")


if __name__ == "__main__":
    sys.exit(main())
