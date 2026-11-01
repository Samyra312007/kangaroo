# Phase 9 — Production §5.5 Track and CacheLib Limitation

Phase 9 implements the production section 5.5 comparison from the paper:
pre-flash admission with probabilistic policies versus ML-style pre-flash
admission. The repository contains a simulator-side reproduction of this
comparison and a documented CacheLib raw-flash track for real CacheLab runs.

## 1. Scope

This phase covers:

- an `ML` pre-flash admission policy in the simulator;
- feature scoring using object popularity, object size, and optional oracle
  future-access counts;
- a deterministic Zipf workload comparison between all-admit, probabilistic
  admission, and ML-style admission;
- a CacheLib/Cachelab hardware-track wrapper that documents the raw-flash
  limitation without fabricating hardware results.

## 2. Simulator-side section 5.5 reproduction

Run:

```bash
bash scripts/build.sh
bash scripts/phase9-simulation.sh
```

Outputs:

```text
results/phase9/section55.csv
results/phase9/logs/*.log
```

The comparison uses three configs:

| Config | Pre-log admission | Meaning |
|---|---|---|
| `configs/phase9/all-admit.cfg` | `Random` with `admitRatio = 1.0` | baseline that admits everything before flash admission |
| `configs/phase9/random.cfg` | `Random` with `admitRatio = 0.9` | probabilistic pre-flash admission |
| `configs/phase9/ml.cfg` | `ML` with feature scoring | ML-style pre-flash admission |

The simulator-side policy uses a simple logistic-style score:

```text
score = oracleWeight * popularity - sizePenalty * size / 4096 + bias
p     = sigmoid(score)
p     = min(p, target_admit_ratio)
```

where popularity comes from `oracle_count` if the trace provides it, then from
`hit_count`, then from a Zipf hot-rank fallback.

Current simulator output:

| Config | Pre-log policy | Miss rate | Flash WAF | WAF vs all-admit | WAF vs random |
|---|---|---:|---:|---:|---:|
| all-admit | Random | `0.316707` | `16.175600` | `0.000%` | `+11.235%` |
| random | Random | `0.323943` | `14.541800` | `-10.100%` | `0.000%` |
| ml | ML | `0.357504` | `8.087600` | `-50.001%` | `-44.384%` |

The exact values are not identical to the production CacheLab numbers because
this simulator uses a synthetic Zipf workload and a lightweight feature model.
The qualitative result is preserved: ML-style pre-flash admission reduces flash
writes substantially compared to all-admit and probabilistic admission.

## 3. CacheLib raw-flash track

The real CacheLab production track requires a raw flash device and a CacheLib
build. Repository wrapper:

```bash
bash scripts/phase9-cachebench.sh
```

By default this reports the limitation and exits successfully. To attempt a real
run:

```bash
bash scripts/phase9-cachebench.sh --run --device /dev/nvme0n1 --clone
```

The script does not fake CacheLab results. If CacheLib, cachebench, or a raw
device is unavailable, Phase 9 is reported as hardware-limited, while the
simulator-side comparison remains available.

## 4. Integration with the main pipeline

`scripts/run-all.sh` includes the simulator-side Phase 9 comparison by default:

```bash
bash scripts/run-all.sh
```

To skip it:

```bash
RUN_PHASE9=0 bash scripts/run-all.sh
```

## 5. Implementation files

- `third_party/Kangaroo/simulator/admission/ml_admission.hpp`
- `third_party/Kangaroo/simulator/admission/admission.cpp`
- `third_party/Kangaroo/simulator/lib/zipf.h`
- `third_party/Kangaroo/simulator/parsers/zipf_parser.hpp`
- `third_party/Kangaroo/simulator/parsers/manual_parser.hpp`
- `configs/phase9/all-admit.cfg`
- `configs/phase9/random.cfg`
- `configs/phase9/ml.cfg`
- `scripts/phase9-simulation.sh`
- `scripts/phase9-simulation.py`
- `scripts/phase9-cachebench.sh`

## 6. Known limitation

The production section 5.5 evaluation in the paper uses CacheLab and real flash
devices. This environment cannot provide that hardware. The repository therefore
implements:

- a simulator-side ML-style pre-flash admission comparison;
- explicit documentation that CacheLab raw-flash execution is not fabricated;
- scripts and config templates for a future CacheLib run when hardware is available.
