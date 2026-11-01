#!/usr/bin/env python3
"""Approximate KLog-to-KSet threshold-admission model for Phase 8.

This implements the simplified Appendix-A Markov/occupancy intuition behind
Theorem 1: when a KSet set write costs a full 4 KB set, only KLog eviction
groups with at least n objects mapping to that set should be admitted. The
model predicts the admission probability and the resulting flash write
amplification for each threshold n.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


def poisson_at_least(lam: float, threshold: int, terms: int = 200) -> float:
    """P(X >= threshold) for X ~ Poisson(lam), clipped to non-negative."""
    if threshold <= 1:
        return 1.0 - math.exp(-lam) if lam > 0 else 0.0

    pk = math.exp(-lam)
    below = pk
    for k in range(1, threshold):
        pk *= lam / k
        below += pk

    return max(0.0, 1.0 - below)


def poisson_conditional_mean(lam: float, threshold: int, terms: int = 200) -> float:
    """E[X | X >= threshold] for X ~ Poisson(lam)."""
    if threshold <= 1:
        return lam

    pk = math.exp(-lam)
    below_full = pk
    below_partial = 0.0
    for k in range(1, threshold):
        pk *= lam / k
        if k < threshold - 1:
            below_partial += pk
        below_full += pk

    p_ge = 1.0 - below_full
    if p_ge <= 0.0:
        return 0.0

    p_ge_minus_one = 1.0 - below_partial
    return (lam * p_ge_minus_one) / p_ge


def simulator_capacity(flash_mb: int, percent_log: float, set_capacity: int) -> tuple[int, int, int]:
    """Reproduce simulator's actual log bytes, set count, and log byte capacity."""
    flash_bytes = flash_mb * 1024 * 1024
    target_log_bytes = int(flash_bytes * percent_log / 100.0)
    set_capacity_bytes = flash_bytes - target_log_bytes
    num_sets = set_capacity_bytes // set_capacity
    actual_log_bytes = flash_bytes - num_sets * set_capacity
    return target_log_bytes, num_sets, actual_log_bytes


def fit_lambda(observed: list[tuple[int, float]], max_lam: float = 25.0, steps: int = 2000) -> float:
    """Fit the occupancy parameter from simulated admission ratios."""
    if not observed:
        return 0.0

    best_lambda = 0.0
    best_error = math.inf
    for i in range(1, steps + 1):
        lam = i * max_lam / steps
        err = sum((poisson_at_least(lam, n) - ratio) ** 2 for n, ratio in observed)
        if err < best_error:
            best_error = err
            best_lambda = lam
    return best_lambda


def set_write_amp(num_sets: int, set_capacity: int, log_bytes: int, occupancy_lambda: float, threshold: int) -> float:
    admission_prob = poisson_at_least(occupancy_lambda, threshold)
    set_write_bytes = num_sets * admission_prob * set_capacity
    return set_write_bytes / log_bytes


def load_sim_rows(path: Path) -> list[dict[str, float]]:
    rows = []
    if not path.exists():
        return rows

    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            try:
                rows.append({
                    "threshold": float(row["threshold"]),
                    "achieved_ratio": float(row["achieved_ratio"]),
                    "waf": float(row["waf"]),
                })
            except (KeyError, ValueError):
                continue
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare simulated KSet threshold behavior to a Markov occupancy model.")
    parser.add_argument("--sim-csv", default="results/sweeps/fig12d_threshold.csv")
    parser.add_argument("--out", default="results/theory/markov_threshold.csv")
    parser.add_argument("--flash-mb", type=int, default=20)
    parser.add_argument("--percent-log", type=float, default=5.0)
    parser.add_argument("--set-capacity", type=int, default=4096)
    parser.add_argument("--avg-obj-size", type=int, default=64)
    parser.add_argument("--log-amp", type=float, default=1.0)
    parser.add_argument("--thresholds", default="1,2,3,4,8")
    args = parser.parse_args()

    sim_rows = load_sim_rows(Path(args.sim_csv))
    sim_by_threshold = {int(row["threshold"]): row for row in sim_rows}
    observed_ratios = [(int(row["threshold"]), row["achieved_ratio"]) for row in sim_rows]
    fitted_lambda = fit_lambda(observed_ratios)

    log_bytes, num_sets, actual_log_bytes = simulator_capacity(args.flash_mb, args.percent_log, args.set_capacity)
    theoretical_lambda = (actual_log_bytes / args.avg_obj_size) / num_sets if num_sets else 0.0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lam = fitted_lambda if fitted_lambda > 0 else theoretical_lambda
    model_base_set_waf = set_write_amp(num_sets, args.set_capacity, actual_log_bytes, lam, 2)
    sim_base = sim_by_threshold.get(2, {}).get("waf", "")
    if sim_base != "" and sim_base > args.log_amp and model_base_set_waf > 0:
        scale = (float(sim_base) - args.log_amp) / model_base_set_waf
    else:
        scale = 1.0

    fields = [
        "threshold",
        "occupancy_lambda",
        "predicted_admission_prob",
        "predicted_expected_group_size",
        "model_set_waf",
        "model_total_waf",
        "calibrated_model_waf",
        "sim_admission_ratio",
        "sim_waf",
        "waf_delta",
        "waf_rel_delta",
    ]

    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for threshold in map(int, args.thresholds.split(",")):
            admission_prob = poisson_at_least(lam, threshold)
            group_size = poisson_conditional_mean(lam, threshold)
            model_set_waf = set_write_amp(num_sets, args.set_capacity, actual_log_bytes, lam, threshold)
            model_total_waf = args.log_amp + model_set_waf
            calibrated_model_waf = args.log_amp + scale * model_set_waf

            sim = sim_by_threshold.get(threshold)
            sim_ratio = sim.get("achieved_ratio", "") if sim else ""
            sim_waf = sim.get("waf", "") if sim else ""

            if sim:
                delta = float(sim_waf) - calibrated_model_waf
                rel_delta = delta / float(sim_waf) if sim_waf else ""
            else:
                delta = ""
                rel_delta = ""

            writer.writerow({
                "threshold": threshold,
                "occupancy_lambda": round(lam, 4),
                "predicted_admission_prob": round(admission_prob, 4),
                "predicted_expected_group_size": round(group_size, 4),
                "model_set_waf": round(model_set_waf, 4),
                "model_total_waf": round(model_total_waf, 4),
                "calibrated_model_waf": round(calibrated_model_waf, 4),
                "sim_admission_ratio": sim_ratio,
                "sim_waf": sim_waf,
                "waf_delta": round(delta, 4) if delta != "" else "",
                "waf_rel_delta": round(rel_delta, 4) if rel_delta != "" else "",
            })

    print(f"model: theoretical lambda={theoretical_lambda:.4f}, fitted lambda={fitted_lambda:.4f}")
    print(f"saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
