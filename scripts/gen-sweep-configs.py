#!/usr/bin/env python3
"""Generate Phase 7 evaluation sweep configurations (paper Figs. 7-12).

Writes one libconfig file per unique run into configs/sweeps/ plus a
manifest.json describing which configs feed which figure. Configs are
de-duplicated: sweeps share anchor runs whenever their parameters match
the paper defaults (Table 2: 5% KLog, p=90%, n=2, 4 KB sets, RRIParoo
3 bits).

Usage:  python3 scripts/gen-sweep-configs.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scale  # noqa: E402  (scripts/scale.py, Appendix B scaling)

CFGDIR = ROOT / "configs" / "sweeps"
JSONDIR = ROOT / "results" / "sweeps" / "json"
MANIFEST = CFGDIR / "manifest.json"

# Paper-default parameters (Table 2), scaled to the simulator's synthetic
# Zipf workload (1 M objects x 64 B = 64 MB working set, 10.24 M requests).
# rrip_bits is not listed here: only Kangaroo uses RRIParoo (3 bits by
# default; SA and LS always use plain FIFO sets / no sets).
BASE = {
    "flash_mb": 20,
    "mem_mb": 5,
    "set_capacity": 4096,
    "percent_log": 5.0,
    "rrip_bits": None,
    "admit_ratio": 0.9,
    "threshold": 2,
    "readmit": 1,
    "flush_block_kb": 256,
    "alpha": 0.9,
    "num_objects_k": 1000,
    "total_k_accesses": 10000,
    "object_scaling": 1.0,
    "mem_overhead_ratio": None,  # None -> omit; simulator default 0.02
    "interval_power": None,      # None -> omit; simulator default 10^6
}

DESIGNS = [("SA", "sa"), ("LS", "ls"), ("KANGAROO", "kangaroo")]


def fmt_float(value: float) -> str:
    """libconfig-friendly float literal (always keeps a decimal point)."""
    text = f"{value:.10g}"
    if "." not in text and "e" not in text and "E" not in text:
        text += ".0"
    return text


def render(name: str, design: str, params: dict) -> str:
    p = params
    lines: list[str] = []

    lines.append("cache = {")
    lines.append(f"  flashSizeMB = {p['flash_mb']};")
    lines.append(f"  memorySizeMB = {p['mem_mb']};")
    if p["mem_overhead_ratio"] is not None:
        lines.append(f"  memOverheadRatio = {fmt_float(p['mem_overhead_ratio'])};")
    lines.append("  slowWarmup = 1;")
    lines.append("};")
    lines.append('memoryCache = { policy = "LRU"; };')

    if design in ("SA", "KANGAROO"):
        lines.append("sets = {")
        lines.append(f"  setCapacity = {p['set_capacity']};")
        if p["rrip_bits"] is not None:
            lines.append(f"  rripBits = {p['rrip_bits']};")
        lines.append("};")

    if design in ("LS", "KANGAROO"):
        lines.append("log = {")
        if design == "KANGAROO":
            lines.append(f"  percentLog = {fmt_float(p['percent_log'])};")
            lines.append(f"  readmit = {p['readmit']};")
            lines.append(f"  flushBlockSizeKB = {p['flush_block_kb']};")
        else:
            # LS baseline: plain log (matches Phase 1 configs; MemLogCache
            # ignores percentLog and uses the whole flash for the log).
            lines.append("  percentLog = 100.0;")
        lines.append("};")

    if design == "KANGAROO":
        lines.append("preLogAdmission = {")
        lines.append('  policy = "Random";')
        lines.append(f"  admitRatio = {fmt_float(p['admit_ratio'])};")
        lines.append("};")
        lines.append("preSetAdmission = {")
        lines.append('  policy = "Threshold";')
        lines.append(f"  threshold = {p['threshold']};")
        lines.append("};")

    lines.append("stats = {")
    lines.append(f'  outputFile = "{JSONDIR / (name + ".out")}";')
    if p["interval_power"] is not None:
        lines.append(f"  collectionIntervalPower = {p['interval_power']};")
    lines.append("};")

    lines.append("trace = {")
    lines.append(f"  alpha = {fmt_float(p['alpha'])};")
    lines.append('  format = "Zipf";')
    lines.append(f"  numObjects = {p['num_objects_k']};")
    lines.append(f"  totalKAccesses = {p['total_k_accesses']};")
    if p["object_scaling"] != 1.0:
        lines.append(f"  objectScaling = {fmt_float(p['object_scaling'])};")
    lines.append("};")

    return "\n".join(lines) + "\n"


def main() -> int:
    configs: dict[str, dict] = {}
    sweeps: dict[str, list[dict]] = {
        "fig07": [],
        "fig08": [],
        "fig09": [],
        "fig10": [],
        "fig11": [],
        "fig12a": [],
        "fig12b": [],
        "fig12c": [],
        "fig12d": [],
    }

    def add(name: str, design: str, **overrides) -> str:
        if name in configs:
            return name
        params = dict(BASE)
        params.update(overrides)
        # RRIParoo is a Kangaroo technique: 3 bits by default, and SA/LS
        # never get it (fifo override passes rrip_bits=None explicitly).
        if design == "KANGAROO":
            if "rrip_bits" not in overrides:
                params["rrip_bits"] = 3
        else:
            params["rrip_bits"] = None
        configs[name] = {"design": design, "params": params}
        return name

    # ------------------------------------------------------------------
    # Anchor runs (paper defaults). The mem5/flash20 anchors double as the
    # Fig. 7 time-series runs (collectionIntervalPower=4 -> one dump per
    # 10 k accesses).
    # ------------------------------------------------------------------
    anchors: dict[str, str] = {}
    for design, tag in DESIGNS:
        anchors[design] = add(f"{tag}-m5-f20", design, interval_power=4)

    # ------------------------------------------------------------------
    # Fig. 9: DRAM sweep (5 -> 64 GB analogue: 1..10 MB at 20 MB flash).
    # ------------------------------------------------------------------
    for mem in (1, 2, 3, 10):
        for design, tag in DESIGNS:
            add(f"{tag}-m{mem}-f20", design, mem_mb=mem)
    for mem in (1, 2, 3, 5, 10):
        for design, tag in DESIGNS:
            sweeps["fig09"].append(
                {"design": design, "mem_mb": mem, "config": f"{tag}-m{mem}-f20"}
            )

    # ------------------------------------------------------------------
    # Fig. 10: flash capacity sweep (10, 20, 50 MB at 5 MB DRAM).
    # ------------------------------------------------------------------
    for flash in (10, 50):
        for design, tag in DESIGNS:
            add(f"{tag}-m5-f{flash}", design, flash_mb=flash)
    for flash in (10, 20, 50):
        for design, tag in DESIGNS:
            sweeps["fig10"].append(
                {"design": design, "flash_mb": flash, "config": f"{tag}-m5-f{flash}"}
            )

    # ------------------------------------------------------------------
    # Fig. 8: Pareto (miss ratio vs device write rate) = union of the DRAM
    # and flash sweep points at matched DRAM/flash budgets.
    # ------------------------------------------------------------------
    for design, tag in DESIGNS:
        for mem in (1, 2, 3, 5, 10):
            sweeps["fig08"].append(
                {
                    "design": design,
                    "mem_mb": mem,
                    "flash_mb": 20,
                    "config": f"{tag}-m{mem}-f20",
                }
            )
        for flash in (10, 50):
            sweeps["fig08"].append(
                {
                    "design": design,
                    "mem_mb": 5,
                    "flash_mb": flash,
                    "config": f"{tag}-m5-f{flash}",
                }
            )

    # ------------------------------------------------------------------
    # Fig. 11: object-size sweep at constant working set (Appendix B).
    # ------------------------------------------------------------------
    for obj_scale in (0.5, 1.0, 2.0, 4.0):
        sp = scale.object_size_sweep_params(obj_scale)
        for design, tag in DESIGNS:
            if obj_scale == 1.0:
                config = anchors[design]
            else:
                suffix = f"x{obj_scale:g}".replace(".", "")
                overhead = (
                    None
                    if design == "SA"
                    else sp["mem_overhead_ratio"]
                )
                config = add(
                    f"{tag}-obj{suffix}-m5-f20",
                    design,
                    object_scaling=sp["object_scaling"],
                    num_objects_k=sp["num_objects_k"],
                    mem_overhead_ratio=overhead,
                )
            sweeps["fig11"].append(
                {
                    "design": design,
                    "scale": obj_scale,
                    "object_bytes": sp["avg_obj_bytes"],
                    "num_objects": sp["num_objects"],
                    "config": config,
                }
            )

    # ------------------------------------------------------------------
    # Fig. 12a: pre-flash admission probability (10% .. 100%).
    # ------------------------------------------------------------------
    for prob in (0.1, 0.3, 0.5, 0.7, 1.0):
        name = f"kangaroo-p{int(round(prob * 100)):03d}"
        add(name, "KANGAROO", admit_ratio=prob)
        sweeps["fig12a"].append({"admit_ratio": prob, "config": name})
    sweeps["fig12a"].append(
        {"admit_ratio": 0.9, "config": anchors["KANGAROO"]}
    )
    sweeps["fig12a"].sort(key=lambda e: e["admit_ratio"])

    # ------------------------------------------------------------------
    # Fig. 12b: FIFO vs RRIParoo (1-4 bits).
    # ------------------------------------------------------------------
    add("kangaroo-fifo", "KANGAROO", rrip_bits=None)
    sweeps["fig12b"].append(
        {"variant": "FIFO", "bits": 0, "config": "kangaroo-fifo"}
    )
    for bits in (1, 2, 4):
        name = f"kangaroo-rrip{bits}"
        add(name, "KANGAROO", rrip_bits=bits)
        sweeps["fig12b"].append(
            {"variant": f"RRIP-{bits}b", "bits": bits, "config": name}
        )
    sweeps["fig12b"].append(
        {"variant": "RRIP-3b", "bits": 3, "config": anchors["KANGAROO"]}
    )
    sweeps["fig12b"].sort(key=lambda e: e["bits"])

    # ------------------------------------------------------------------
    # Fig. 12c: KLog size as % of flash (0% = SA baseline).
    # ------------------------------------------------------------------
    sweeps["fig12c"].append(
        {"percent_log": 0.0, "design": "SA", "config": anchors["SA"]}
    )
    for pct in (1, 3, 7, 9):
        name = f"kangaroo-log{pct:02d}"
        add(name, "KANGAROO", percent_log=float(pct))
        sweeps["fig12c"].append(
            {"percent_log": float(pct), "design": "KANGAROO", "config": name}
        )
    sweeps["fig12c"].append(
        {"percent_log": 5.0, "design": "KANGAROO", "config": anchors["KANGAROO"]}
    )
    sweeps["fig12c"].sort(key=lambda e: e["percent_log"])

    # ------------------------------------------------------------------
    # Fig. 12d: KSet admission threshold (n = 2 is the paper default).
    # ------------------------------------------------------------------
    for n in (3, 4, 8):
        name = f"kangaroo-thr{n:02d}"
        add(name, "KANGAROO", threshold=n)
        sweeps["fig12d"].append({"threshold": n, "config": name})
    sweeps["fig12d"].append(
        {"threshold": 2, "config": anchors["KANGAROO"]}
    )
    sweeps["fig12d"].sort(key=lambda e: e["threshold"])

    # ------------------------------------------------------------------
    # Fig. 7: miss ratio over time (windowed from the interval dumps of
    # the three anchor runs).
    # ------------------------------------------------------------------
    for design, tag in DESIGNS:
        sweeps["fig07"].append(
            {"design": design, "config": anchors[design]}
        )

    # ------------------------------------------------------------------
    # Emit configs + manifest.
    # ------------------------------------------------------------------
    CFGDIR.mkdir(parents=True, exist_ok=True)
    JSONDIR.mkdir(parents=True, exist_ok=True)

    for name, entry in sorted(configs.items()):
        (CFGDIR / f"{name}.cfg").write_text(render(name, entry["design"], entry["params"]))

    manifest = {
        "generated_by": "scripts/gen-sweep-configs.py",
        "base": {
            "base_obj_bytes": scale.BASE_OBJ_BYTES,
            "base_num_objects": scale.BASE_NUM_OBJECTS_K * 1000,
            "total_requests": BASE["total_k_accesses"] * 1024,
            "full_server_request_rate": round(
                scale.full_server_request_rate(1.0), 1
            ),
        },
        "configs": {
            name: {
                "design": entry["design"],
                "params": entry["params"],
                "file": f"configs/sweeps/{name}.cfg",
            }
            for name, entry in sorted(configs.items())
        },
        "sweeps": sweeps,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"wrote {len(configs)} configs to {CFGDIR}")
    print(f"wrote {MANIFEST}")
    for fig, entries in sweeps.items():
        print(f"  {fig}: {len(entries)} points")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
