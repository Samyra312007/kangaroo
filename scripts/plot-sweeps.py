#!/usr/bin/env python3
"""Render the Phase 7 figures (paper Figs. 7-12) from collected CSVs.

Requires matplotlib + numpy (scripts/setup-plot-deps.sh, run automatically
by scripts/make-figures.sh).

Usage:  .venv/bin/python scripts/plot-sweeps.py
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results" / "sweeps"
FIGURES = ROOT / "figures"

# Match the artifact's palette (graph-scripts/parameters.py).
COLORS = {"KANGAROO": "tab:orange", "SA": "#000080", "LS": "tab:cyan"}
DESIGNS = ["SA", "LS", "KANGAROO"]
LABELS = {"KANGAROO": "Kangaroo", "SA": "SA", "LS": "LS"}
DEVICE_BUDGET_MBPS = 62.5  # paper's WD SN840 write budget


def read_csv(name: str) -> list[dict]:
    with (RESULTS / name).open() as handle:
        return list(csv.DictReader(handle))


def fnum(rows: list[dict], key: str) -> list[float]:
    return [float(r[key]) for r in rows]


def style(ax: plt.Axes) -> None:
    ax.grid(True, axis="y", alpha=0.3, linewidth=0.6)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


def save(fig: plt.Axes, name: str) -> None:
    path = FIGURES / name
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")


def fig07() -> None:
    rows = read_csv("fig07_timeseries.csv")
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    for design in DESIGNS:
        pts = [r for r in rows if r["design"] == design]
        days = fnum(pts, "day")
        windowed = np.array(fnum(pts, "window_miss_rate"))
        # Smooth the 10 k-access windows for readability.
        kernel = np.ones(25) / 25
        smooth = np.convolve(windowed, kernel, mode="valid")
        ax.plot(
            days[24:],
            smooth,
            color=COLORS[design],
            label=LABELS[design],
            linewidth=1.6,
        )
    ax.set_xlabel("Trace day (10.24 M requests mapped to 7 days)")
    ax.set_ylabel("Windowed miss ratio")
    ax.set_title("Miss ratio over time (Fig. 7 analogue)")
    ax.legend(frameon=False)
    style(ax)
    save(fig, "fig07_miss_ratio_over_time.pdf")


def fig08() -> None:
    rows = read_csv("fig08_pareto.csv")
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    for design in DESIGNS:
        pts = [r for r in rows if r["design"] == design]
        dram_pts = sorted(
            [p for p in pts if p["flash_mb"] == "20"],
            key=lambda p: int(p["mem_mb"]),
        )
        flash_pts = [p for p in pts if p["flash_mb"] != "20"]
        if dram_pts:
            ax.plot(
                fnum(dram_pts, "dev_write_mbps"),
                fnum(dram_pts, "miss_rate"),
                color=COLORS[design],
                marker="o",
                markersize=5,
                linewidth=1.4,
                label=f"{LABELS[design]} (DRAM sweep)",
            )
        if flash_pts:
            ax.scatter(
                fnum(flash_pts, "dev_write_mbps"),
                fnum(flash_pts, "miss_rate"),
                color=COLORS[design],
                marker="^",
                s=45,
                zorder=5,
                label=f"{LABELS[design]} (flash sweep)",
            )
    ax.axvline(
        DEVICE_BUDGET_MBPS,
        color="red",
        linestyle="--",
        linewidth=1.0,
        label=f"device budget ({DEVICE_BUDGET_MBPS:g} MB/s)",
    )
    ax.set_xlabel("Device write rate (MB/s)")
    ax.set_ylabel("Miss ratio")
    ax.set_title("Miss ratio vs device write rate (Fig. 8 analogue)")
    ax.legend(frameon=False, fontsize=8, ncol=2)
    style(ax)
    save(fig, "fig08_pareto.pdf")


def fig09() -> None:
    rows = read_csv("fig09_dram_sweep.csv")
    fig, ax = plt.subplots(figsize=(6.0, 4.2))
    for design in DESIGNS:
        pts = sorted(
            [r for r in rows if r["design"] == design],
            key=lambda r: int(r["mem_mb"]),
        )
        ax.plot(
            fnum(pts, "mem_mb"),
            fnum(pts, "miss_rate"),
            color=COLORS[design],
            marker="o",
            markersize=5,
            label=LABELS[design],
        )
    ax.set_xscale("log", base=2)
    ax.set_xlabel("DRAM budget (MB)")
    ax.set_ylabel("Miss ratio")
    ax.set_title("DRAM sensitivity (Fig. 9 analogue)")
    ax.legend(frameon=False)
    style(ax)
    save(fig, "fig09_dram_sweep.pdf")


def fig10() -> None:
    rows = read_csv("fig10_flash_sweep.csv")
    fig, ax = plt.subplots(figsize=(6.0, 4.2))
    for design in DESIGNS:
        pts = sorted(
            [r for r in rows if r["design"] == design],
            key=lambda r: int(r["flash_mb"]),
        )
        ax.plot(
            fnum(pts, "flash_mb"),
            fnum(pts, "miss_rate"),
            color=COLORS[design],
            marker="o",
            markersize=5,
            label=LABELS[design],
        )
    ax.set_xscale("log", base=2)
    ax.set_xlabel("Flash capacity (MB)")
    ax.set_ylabel("Miss ratio")
    ax.set_title("Flash capacity sensitivity (Fig. 10 analogue)")
    ax.legend(frameon=False)
    style(ax)
    save(fig, "fig10_flash_sweep.pdf")


def fig11() -> None:
    rows = read_csv("fig11_objsize_sweep.csv")
    fig, ax = plt.subplots(figsize=(6.0, 4.2))
    for design in DESIGNS:
        pts = sorted(
            [r for r in rows if r["design"] == design],
            key=lambda r: float(r["object_bytes"]),
        )
        ax.plot(
            fnum(pts, "object_bytes"),
            fnum(pts, "miss_rate"),
            color=COLORS[design],
            marker="o",
            markersize=5,
            label=LABELS[design],
        )
    ax.set_xscale("log", base=2)
    ax.set_xlabel("Average object size (bytes, constant working set)")
    ax.set_ylabel("Miss ratio")
    ax.set_title("Object size sensitivity (Fig. 11 analogue)")
    ax.legend(frameon=False)
    style(ax)
    save(fig, "fig11_objsize_sweep.pdf")


def fig12a() -> None:
    rows = read_csv("fig12a_admission_prob.csv")
    rows.sort(key=lambda r: float(r["admit_ratio"]))
    x = fnum(rows, "admit_ratio")
    fig, ax1 = plt.subplots(figsize=(6.2, 4.2))
    ax2 = ax1.twinx()
    ax1.plot(x, fnum(rows, "miss_rate"), color="tab:orange", marker="o",
             markersize=5, label="miss ratio")
    ax2.plot(x, fnum(rows, "dev_write_mbps"), color="tab:blue", marker="s",
             markersize=5, linestyle="--", label="device write rate")
    ax1.set_xlabel("Pre-flash admission probability")
    ax1.set_ylabel("Miss ratio", color="tab:orange")
    ax2.set_ylabel("Device write rate (MB/s)", color="tab:blue")
    ax1.set_title("Pre-flash admission probability (Fig. 12a)")
    ax1.grid(True, axis="y", alpha=0.3, linewidth=0.6)
    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [l.get_label() for l in lines], frameon=False, loc="upper left")
    fig.savefig(FIGURES / "fig12a_admission_prob.pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {FIGURES / 'fig12a_admission_prob.pdf'}")


def fig12b() -> None:
    rows = read_csv("fig12b_rrip_bits.csv")
    rows.sort(key=lambda r: int(r["bits"]))
    labels = [r["variant"] for r in rows]
    values = fnum(rows, "miss_rate")
    fig, ax = plt.subplots(figsize=(6.0, 4.2))
    ax.bar(labels, values, color=["gray"] + ["tab:orange"] * (len(labels) - 1),
           width=0.6, edgecolor="white")
    for i, value in enumerate(values):
        ax.text(i, value, f"{value:.3f}", ha="center", va="bottom", fontsize=8)
    ax.set_xlabel("Eviction policy (RRIParoo bits)")
    ax.set_ylabel("Miss ratio")
    ax.set_title("FIFO vs RRIParoo (Fig. 12b)")
    ax.grid(True, axis="y", alpha=0.3, linewidth=0.6)
    ax.set_axisbelow(True)
    save(fig, "fig12b_rrip_bits.pdf")


def fig12c() -> None:
    rows = read_csv("fig12c_log_size.csv")
    rows.sort(key=lambda r: float(r["percent_log"]))
    x = fnum(rows, "percent_log")
    fig, ax1 = plt.subplots(figsize=(6.2, 4.2))
    ax2 = ax1.twinx()
    ax1.plot(x, fnum(rows, "miss_rate"),
             color="tab:orange", marker="o", markersize=5, label="miss ratio")
    ax2.plot(x, fnum(rows, "waf"), color="tab:blue", marker="s", markersize=5,
             linestyle="--", label="write amplification (alwa)")
    ax1.set_xlabel("KLog size (% of flash)")
    ax1.set_ylabel("Miss ratio", color="tab:orange")
    ax2.set_ylabel("Flash write amplification", color="tab:blue")
    ax1.set_title("KLog size sensitivity (Fig. 12c)")
    ax1.grid(True, axis="y", alpha=0.3, linewidth=0.6)
    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [l.get_label() for l in lines], frameon=False, loc="upper left")
    save(fig, "fig12c_log_size.pdf")


def fig12d() -> None:
    rows = read_csv("fig12d_threshold.csv")
    rows.sort(key=lambda r: int(r["threshold"]))
    x = fnum(rows, "threshold")
    fig, ax1 = plt.subplots(figsize=(6.2, 4.2))
    ax2 = ax1.twinx()
    ax1.plot(x, fnum(rows, "miss_rate"), color="tab:orange", marker="o",
             markersize=5, label="miss ratio")
    ax2.plot(x, fnum(rows, "waf"), color="tab:blue", marker="s", markersize=5,
             linestyle="--", label="write amplification (alwa)")
    ax1.set_xlabel("KSet admission threshold (n objects)")
    ax1.set_ylabel("Miss ratio", color="tab:orange")
    ax2.set_ylabel("Flash write amplification", color="tab:blue")
    ax1.set_title("KSet admission threshold (Fig. 12d)")
    ax1.grid(True, axis="y", alpha=0.3, linewidth=0.6)
    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [l.get_label() for l in lines], frameon=False, loc="upper left")
    save(fig, "fig12d_threshold.pdf")


def main() -> int:
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig07()
    fig08()
    fig09()
    fig10()
    fig11()
    fig12a()
    fig12b()
    fig12c()
    fig12d()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
