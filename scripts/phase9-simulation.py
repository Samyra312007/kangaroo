#!/usr/bin/env python3
import csv
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.environ.get(
    "PHASE9_BIN",
    os.path.join(ROOT, "third_party/Kangaroo/simulator/bin/cache"),
)
CONFIG_DIR = os.path.join(ROOT, "configs/phase9")
OUT_DIR = os.path.join(ROOT, "results/phase9")
LOG_DIR = os.path.join(OUT_DIR, "logs")
OUT_CSV = os.path.join(OUT_DIR, "section55.csv")

CONFIGS = [
    {"config": "all-admit", "label": "all-admit", "policy": "Random", "admit_ratio": "1.0"},
    {"config": "random", "label": "probabilistic", "policy": "Random", "admit_ratio": "0.9"},
    {"config": "ml", "label": "ML-style", "policy": "ML", "admit_ratio": "0.9"},
]

MISS_RE = re.compile(r"^Miss Rate: ([0-9.]+) Flash Write Amp: ([^ ]+)$", re.MULTILINE)


def run_config(cfg_name):
    cfg = os.path.join(CONFIG_DIR, cfg_name + ".cfg")
    log = os.path.join(LOG_DIR, cfg_name + ".log")
    os.makedirs(LOG_DIR, exist_ok=True)

    with open(log, "w") as f:
        subprocess.run(
            [BIN, cfg],
            stdout=f,
            stderr=subprocess.STDOUT,
            cwd=ROOT,
            check=True,
        )

    text = open(log, "r").read()
    matches = MISS_RE.findall(text)
    if not matches:
        raise RuntimeError(f"no Miss Rate/WAF line found in {log}")

    miss, waf = matches[-1]
    return float(miss), float(waf)


def pct_change(value, base):
    if base == 0:
        return ""
    return f"{((value - base) / base) * 100:.3f}"


def main():
    stats = {}
    configs = []

    for cfg in CONFIGS:
        miss, waf = run_config(cfg["config"])
        stats[cfg["config"]] = (miss, waf)
        configs.append(cfg)

    rows = []
    for cfg in configs:
        miss, waf = stats[cfg["config"]]
        rows.append({
            "config": cfg["config"],
            "label": cfg["label"],
            "policy": cfg["policy"],
            "admit_ratio": cfg["admit_ratio"],
            "miss_rate": f"{miss:.6f}",
            "flash_waf": f"{waf:.6f}",
            "waf_vs_all": pct_change(waf, stats["all-admit"][1]),
            "waf_vs_random": pct_change(waf, stats["random"][1]),
            "miss_vs_all": pct_change(miss, stats["all-admit"][0]),
        })

    os.makedirs(OUT_DIR, exist_ok=True)
    fieldnames = [
        "config",
        "label",
        "policy",
        "admit_ratio",
        "miss_rate",
        "flash_waf",
        "waf_vs_all",
        "waf_vs_random",
        "miss_vs_all",
    ]

    with open(OUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"phase9: simulation comparison written to {OUT_CSV}")
    print(open(OUT_CSV).read())


if __name__ == "__main__":
    main()
