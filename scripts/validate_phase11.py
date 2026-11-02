#!/usr/bin/env python3
import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BIN = REPO / "third_party/Kangaroo/simulator/bin/cache"
CONFIG_DIR = REPO / "configs/phase11"
RESULT_DIR = REPO / "results/phase11"
LOG_DIR = RESULT_DIR / "logs"
SUMMARY_PATH = RESULT_DIR / "summary.json"

MISS_RE = re.compile(r"Miss Rate:\s+([0-9]+(?:\.[0-9]+)?)")
WAF_RE = re.compile(r"Flash Write Amp:\s+([0-9]+(?:\.[0-9]+)?)")
FINAL_RE = re.compile(r"AdaKanga final: (.*)")


def run_config(config_path):
    proc = subprocess.run([str(BIN), str(config_path)], text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"cache failed for {config_path}: {proc.stderr}")

    miss_values = [float(x) for x in MISS_RE.findall(proc.stdout)]
    waf_values = [float(x) for x in WAF_RE.findall(proc.stdout)]
    final_match = FINAL_RE.search(proc.stdout)

    stats_path = LOG_DIR / f"{config_path.stem}.out"
    final_stats = {}
    if stats_path.exists():
        text = stats_path.read_text()
        decoder = json.JSONDecoder()
        idx = 0
        objects = []
        while idx < len(text):
            while idx < len(text) and text[idx].isspace():
                idx += 1
            if idx >= len(text):
                break
            obj, end = decoder.raw_decode(text, idx)
            objects.append(obj)
            idx = end

        if objects:
            final = objects[-1]
            final_stats["adaptive"] = final.get("Adaptive.preLogAdmission", {})
            final_stats["log"] = final.get("log", {})
            final_stats["sets"] = final.get("sets", {})
            final_stats["memCache"] = final.get("memCache", {})
            final_stats["global"] = final.get("global", {})

    log_stats = final_stats.get("log", {})
    set_stats = final_stats.get("sets", {})

    return {
        "config": config_path.name,
        "finalMissRate": miss_values[-1] if miss_values else None,
        "finalFlashWriteAmp": waf_values[-1] if waf_values else None,
        "finalAdaKanga": final_match.group(1) if final_match else None,
        "expiredMisses": final_stats.get("global", {}).get("expiredMisses", 0),
        "expiredMissSize": final_stats.get("global", {}).get("expiredMissSize", 0),
        "expiredDrops": log_stats.get("expiredDrops", 0) + set_stats.get("expiredDrops", 0),
        "expiredBytesDropped": log_stats.get("expiredBytesDropped", 0) + set_stats.get("expiredBytesDropped", 0),
        "expiredSkippedStores": log_stats.get("expiredSkippedStores", 0) + set_stats.get("expiredSkippedStores", 0),
        "expiredBytesSkipped": log_stats.get("expiredBytesSkipped", 0) + set_stats.get("expiredBytesSkipped", 0),
        "logStoreRequestedBytes": log_stats.get("stores_requested_bytes", 0),
        "setStoreRequestedBytes": set_stats.get("stores_requested_bytes", 0),
        "logBytesWritten": log_stats.get("bytes_written", 0),
        "setBytesWritten": set_stats.get("bytes_written", 0),
        "totalFlashBytesWritten": log_stats.get("bytes_written", 0) + set_stats.get("bytes_written", 0),
        "logLiveBytes": log_stats.get("current_size", 0),
        "setLiveBytes": set_stats.get("current_size", 0),
        "liveFlashBytes": log_stats.get("current_size", 0) + set_stats.get("current_size", 0),
        "shortTtlRejected": final_stats.get("adaptive", {}).get("shortTtlRejected", 0),
        "shortTtlRejectedBytes": final_stats.get("adaptive", {}).get("shortTtlRejectedBytes", 0),
        "finalStats": final_stats,
    }


def main():
    configs = sorted(CONFIG_DIR.glob("*.cfg"))
    results = {run_config(config)["config"]: run_config(config) for config in configs}

    ttl = results["ttl.cfg"]
    vanilla = results["vanilla.cfg"]
    no_short = results["ttl_no_short.cfg"]
    long_ttl = results["long_ttl_ttl.cfg"]
    long_vanilla = results["long_ttl_vanilla.cfg"]
    long_only_ttl = results["long_only_ttl.cfg"]
    long_only_vanilla = results["long_only_vanilla.cfg"]

    flash_reduction = vanilla["totalFlashBytesWritten"] > ttl["totalFlashBytesWritten"]
    waf_reduction = vanilla["finalFlashWriteAmp"] > ttl["finalFlashWriteAmp"]
    live_reduction = vanilla["liveFlashBytes"] > ttl["liveFlashBytes"]

    long_only_delta = abs(long_only_ttl["finalMissRate"] - long_only_vanilla["finalMissRate"]) / max(long_only_vanilla["finalMissRate"], 1e-12)
    long_ttl_delta = abs(long_ttl["finalMissRate"] - long_vanilla["finalMissRate"]) / max(long_vanilla["finalMissRate"], 1e-12)

    summary = {
        "configs": results,
        "criteria": {
            "expiredObjectsAreNeverHits": ttl["expiredMisses"] > 0 and no_short["expiredMisses"] > 0,
            "shortTtlAdmissionRejected": ttl["shortTtlRejected"] > 0 and ttl["shortTtlRejectedBytes"] > 0,
            "shortTtlFlashWritesReducedVsVanilla": flash_reduction,
            "shortTtlFlashWriteAmpReducedVsVanilla": waf_reduction,
            "liveFlashBytesReducedVsVanilla": live_reduction,
            "longOnlyMissNoRegression": long_only_delta <= 0.02,
            "longTtlMissNoRegression": long_ttl_delta <= 0.02,
        },
        "metrics": {
            "vanilla": {
                "missRate": vanilla["finalMissRate"],
                "flashWriteAmp": vanilla["finalFlashWriteAmp"],
                "totalFlashBytesWritten": vanilla["totalFlashBytesWritten"],
                "liveFlashBytes": vanilla["liveFlashBytes"],
            },
            "ttl": {
                "missRate": ttl["finalMissRate"],
                "flashWriteAmp": ttl["finalFlashWriteAmp"],
                "totalFlashBytesWritten": ttl["totalFlashBytesWritten"],
                "liveFlashBytes": ttl["liveFlashBytes"],
                "expiredMisses": ttl["expiredMisses"],
                "shortTtlRejected": ttl["shortTtlRejected"],
                "shortTtlRejectedBytes": ttl["shortTtlRejectedBytes"],
            },
            "ttlNoShort": {
                "missRate": no_short["finalMissRate"],
                "flashWriteAmp": no_short["finalFlashWriteAmp"],
                "totalFlashBytesWritten": no_short["totalFlashBytesWritten"],
                "liveFlashBytes": no_short["liveFlashBytes"],
                "expiredMisses": no_short["expiredMisses"],
            },
            "longOnly": {
                "vanillaMissRate": long_only_vanilla["finalMissRate"],
                "ttlMissRate": long_only_ttl["finalMissRate"],
                "relativeDelta": long_only_delta,
            },
            "longTtl": {
                "vanillaMissRate": long_vanilla["finalMissRate"],
                "ttlMissRate": long_ttl["finalMissRate"],
                "relativeDelta": long_ttl_delta,
            },
        },
    }

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n")

    print(json.dumps(summary["criteria"], indent=2))
    print(
        f"Vanilla: miss={vanilla['finalMissRate']:.6f}, "
        f"waf={vanilla['finalFlashWriteAmp']:.6f}, "
        f"flashBytes={vanilla['totalFlashBytesWritten']:.0f}, "
        f"live={vanilla['liveFlashBytes']:.0f}"
    )
    print(
        f"TTL: miss={ttl['finalMissRate']:.6f}, "
        f"waf={ttl['finalFlashWriteAmp']:.6f}, "
        f"flashBytes={ttl['totalFlashBytesWritten']:.0f}, "
        f"live={ttl['liveFlashBytes']:.0f}, "
        f"shortRejected={ttl['shortTtlRejected']:.0f}"
    )
    print(f"Wrote {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
