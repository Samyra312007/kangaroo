# Phase 8 — Correctness, Sanitizers, and Threshold Theory

Phase 8 turns the simulator from "runs and reproduces paper trends" into a
validated implementation with explicit regression coverage, sanitizer
validation, and a theory check for the KSet admission threshold.

## 1. Scope

This phase covers:

- exact manual-trace edge cases,
- sanitizer-enabled simulator builds,
- ASan/UBSan execution of the golden trace and edge cases,
- a simplified Markov occupancy model for KSet threshold admission,
- comparison between the model and the simulated threshold sweep from
  `results/sweeps/fig12d_threshold.csv`.

## 2. Verification commands

```bash
bash scripts/build.sh
bash tests/run_golden.sh
bash tests/run_edge_cases.sh
bash scripts/build-asan.sh
bash tests/run_sanitizer.sh
python3 scripts/markov-threshold.py
bash scripts/run-all.sh 8
```

`scripts/run-all.sh 8` is the normal top-level reproduction entry point. It now
includes golden tests, edge tests, and the Markov threshold model output. If
sanitizers are requested:

```bash
SANITIZE=1 bash scripts/run-all.sh 8
```

## 3. Correctness edge cases

`tests/run_edge_cases.sh` runs deterministic manual traces under
`tests/configs/edge/`.

| Case | Expected behavior | Expected miss rate |
|---|---|---:|
| `empty` | no requests, cache remains valid | `0` |
| `all_miss` | every request misses | `1` |
| `all_hit` | DRAM resident object is hit repeatedly | `0.1` |
| `zero_byte` | zero-size request does not crash or silently hit | `1` |
| `threshold_one` | threshold admission with `n = 1` is accepted | `0.1` |
| `single_segment_log` | log flush with a single segment behaves correctly | `1` |
| `over_capacity` | request larger than cache capacity is handled without crash | `1` |
| `duplicate_keys` | repeated key does not corrupt hit/miss accounting | `0.1` |

Implementation changes relevant to these tests:

- `third_party/Kangaroo/simulator/parsers/manual_parser.hpp` adds exact flat
  manual traces.
- `third_party/Kangaroo/simulator/parsers/parser.cpp` wires `trace.format = "Manual"`
  into the simulator.
- `third_party/Kangaroo/simulator/caches/cache.cpp` handles empty traces and
  zero-size requests.
- `third_party/Kangaroo/simulator/admission/threshold.hpp` allows threshold
  admission when `n = 1`.

## 4. Sanitizer pipeline

The sanitizer target is built as:

```bash
scripts/build-asan.sh
```

This produces:

```text
third_party/Kangaroo/simulator/bin/asan/cache
```

`tests/run_sanitizer.sh` runs:

- golden regression config under ASan/UBSan,
- all edge-case configs under ASan/UBSan,
- a check that no sanitizer diagnostics such as `AddressSanitizer`,
  `UndefinedBehaviorSanitizer`, runtime errors, or leaks appear.

Current result: PASS.

## 5. Markov threshold model

`scripts/markov-threshold.py` implements a simplified Appendix-A occupancy model
for the KSet admission threshold.

The model assumes that each KSet set has an occupancy drawn from a Poisson
distribution:

```text
X ~ Poisson(lambda)
```

A set is admitted to KSet only if:

```text
X >= n
```

where `n` is the threshold. The model estimates:

- admission probability, `P(X >= n)`;
- expected admitted group size, `E[X | X >= n]`;
- KSet write amplification contribution;
- calibrated total flash WAF.

The calibration step uses the simulated threshold sweep. The simulated WAF at
threshold `n = 2` is used as the anchor, then the threshold-dependent admission
probability scales the set-write contribution.

This is intentionally approximate. The simulator's actual WAF denominator is
implementation-specific and includes pre-log admission bytes, set write bytes,
log write bytes, and nonuniform Zipf popularity effects. The model is not meant
to reproduce every absolute simulator number; it is meant to reproduce the
threshold direction and qualitative curvature.

Output:

```text
results/theory/markov_threshold.csv
```

Example output:

| Threshold | Predicted admission prob | Calibrated model WAF | Simulated WAF |
|---:|---:|---:|---:|
| 1 | 0.9902 | 15.1676 | — |
| 2 | 0.9449 | 14.5189 | 14.5189 |
| 3 | 0.8400 | 13.0187 | 12.2445 |
| 4 | 0.6784 | 10.7058 | 8.4011 |
| 8 | 0.0972 | 2.3913 | 1.2324 |

The model matches the threshold direction strongly: increasing the threshold
reduces flash write amplification. Absolute values drift because the simulator's
occupancy is not perfectly Poisson and because the WAF accounting includes
implementation-specific factors.

## 6. Phase 8 conclusion

Phase 8 is complete for the simulator track:

- exact correctness edge cases pass,
- sanitizer build and execution pass,
- threshold theory is documented and generated automatically,
- the reproduction pipeline includes Phase 8 verification.
