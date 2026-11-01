# Kangaroo — End-to-End Implementation

<p align="center">
  <img src="assets/logo.svg" alt="Kangaroo logo" width="220"/>
</p>

<p align="center">
  <a href="https://github.com/Samyra312007/kangaroo/actions"><img alt="build" src="https://img.shields.io/badge/build-passing-brightgreen"/></a>
  <a href="LICENSE"><img alt="license" src="https://img.shields.io/badge/license-MIT-blue"/></a>
  <img alt="C++14" src="https://img.shields.io/badge/C%2B%2B-14-00599C"/>
  <img alt="Python 3" src="https://img.shields.io/badge/python-3.12+-3776AB"/>
  <img alt="platform" src="https://img.shields.io/badge/platform-Linux-lightgrey"/>
</p>

> Working implementation of **Kangaroo: Caching Billions of Tiny Objects on Flash**
> (SOSP '21), plus two planned extensions (adaptive admission and TTL-aware
> caching). See [`plan.md`](plan.md) for the full phase-by-phase roadmap.

This repository builds and drives the reference **simulator** from the paper's
artifact. Baselines **SA** (set-associative) and **LS** (log-structured) are
exercised here; Kangaroo itself (KLog + KSet) ships in the vendored simulator
and is evaluated in later phases.

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Project Layout](#project-layout)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Results](#results)
- [Testing](#testing)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)
- [Citation](#citation)

## Features

- **Reproducible build** with no root privileges: SCons and libconfig++ are
  bootstrapped into `.deps/`.
- **Three cache designs** selectable purely by configuration: SA (`memoryCache` +
  `sets`), LS (`memoryCache` + `log`), and Kangaroo (`memoryCache` + `log` +
  `sets`).
- **Scripted evaluation pipeline**: generate configs, run in parallel, collect
  into CSV, render paper-style figures.
- **Golden-trace regression test** for bit-for-bit reproducibility.
- **Two extensions beyond the paper**: *AdaKanga* (online adaptive admission)
  and *Kangaroo-TTL* (expiry-aware caching).

## Architecture

Kangaroo stacks three caches in front of the backend:

| Layer | What it is | Role | DRAM cost |
|---|---|---|---|
| DRAM cache | Tiny in-memory LRU cache | Absorbs the hottest objects | < 1% of capacity |
| KLog | Small log-structured flash cache (~5% of flash) with a partitioned DRAM index | Write-efficient staging area, WAF ~ 1x | ~48 bits/object |
| KSet | Large set-associative flash cache (~95% of flash), 4 KB sets, no DRAM index | Bulk storage; per-set Bloom filter avoids wasted reads | ~4 bits/object |

Lookup path: DRAM cache -> KLog -> KSet. Insert path: DRAM cache -> pre-flash
admission -> KLog -> (on eviction) threshold admission -> KSet.

## Project Layout

```
plan.md                     phase-wise implementation plan
report.md                   Phase 7 reproduction report and Phase 8 validation notes
docs/phase8.md              Phase 8 correctness, sanitizer, and threshold-model notes
assets/logo.svg             project logo
configs/baselines/          generated SA / LS simulator configurations (Phase 1)
configs/golden/             golden regression config
configs/sweeps/             Phase 7 sweep configurations + manifest
results/baselines/          baseline logs + collected CSV (Phase 1)
results/golden/             golden expected output
results/sweeps/             Phase 7 CSVs (Figs. 7-12 data, Tables 1 & 4)
results/theory/             Phase 8 Markov/threshold model output
figures/                    Phase 7 PDF figures (paper Figs. 7-12 analogues)
scripts/
  setup-deps.sh             build SCons + libconfig++ into .deps/ (no root)
  build.sh                  build third_party/Kangaroo/simulator/bin/cache
  build-asan.sh             sanitizer build (Phase 8)
  run-baselines.sh          run all baseline configs, capture stdout
  run-all.sh                one-command full reproduction
  collect.py                parse logs -> results/baselines/baseline_results.csv
  gen-sweep-configs.py      generate Phase 7 sweep configs + manifest
  run-sweeps.sh             parallel sweep runner (resumable)
  collect-sweeps.py         logs + stats JSON -> per-figure CSVs
  scale.py                  Appendix B trace-scaling calculator (Table 4)
  markov-threshold.py       Phase 8 threshold occupancy model and validation table
  setup-plot-deps.sh        create .venv with matplotlib/numpy
  make-figures.sh           render figures/*.pdf from the CSVs
tests/
  run_golden.sh             golden-trace regression test
  golden.expected           committed expected steady-state line
  run_edge_cases.sh         exact manual edge-case traces
  configs/edge/            Phase 8 edge-case configs
  run_sanitizer.sh         ASan/UBSan smoke tests for golden + edge configs
third_party/Kangaroo/       vendored upstream simulator (with build fixes)
docs/
  phase1.md                Phase 0/1 notes, build fixes, results
  report.tex                research-style status report
```

## Requirements

- Linux with `g++` (C++14+), `python3`, `curl`, `make`, and network access.
- No root required — dependencies are built into `.deps/`.

## Quick Start

```bash
scripts/setup-deps.sh     # SCons (venv) + libconfig++ 1.7.3 (from source)
scripts/build.sh          # -> third_party/Kangaroo/simulator/bin/cache
scripts/run-baselines.sh 8 # 8 parallel jobs
python3 scripts/collect.py # -> results/baselines/baseline_results.csv
```

Or, in one command:

```bash
scripts/run-all.sh 8
```

### Phase 7 sweep (paper reproduction)

```bash
python3 scripts/gen-sweep-configs.py    # 46 configs -> configs/sweeps/
bash scripts/run-sweeps.sh 12           # resumable; FORCE=1 to re-run all
python3 scripts/collect-sweeps.py       # -> results/sweeps/*.csv
bash scripts/make-figures.sh            # -> figures/*.pdf
```

Analysis of every figure against the paper's reported numbers lives in
[`report.md`](report.md).

### Phase 8 validation

```bash
bash tests/run_edge_cases.sh
bash scripts/build-asan.sh
bash tests/run_sanitizer.sh
python3 scripts/markov-threshold.py --out results/theory/markov_threshold.csv
```

`scripts/markov-threshold.py` compares the simulated KSet threshold sweep to a
Poisson occupancy model inspired by Appendix A / Theorem 1. It writes a table
under `results/theory/` and is included automatically in `scripts/run-all.sh`.

## Usage

```bash
third_party/Kangaroo/simulator/bin/cache <config-file.cfg>
```

A config is a libconfig file selecting the design via which sections are present
(`memoryCache`, `log`, `sets`) plus knobs such as `cache.flashSizeMB`,
`cache.memorySizeMB`, `trace.alpha`, etc. See `configs/baselines/` for examples.

## Results

Phase 1 baseline sweep (Zipf, alpha = 0.9, 1 000 000 objects, ~10.24 M
requests), steady state, 20 MB flash:

| Design | DRAM 1 MB | 2 MB | 3 MB | 5 MB | 10 MB | WAF |
|---|---|---|---|---|---|---|
| SA | 0.2421 | 0.2333 | 0.2247 | 0.2087 | 0.1746 | 64.0 |
| LS | 0.2463 | 0.2374 | 0.2286 | 0.2124 | 0.1774 | 1.0 |

Full table: `results/baselines/baseline_results.csv`.

**Phase 7 — Kangaroo vs. baselines** (Zipf, alpha 0.9, 1 M objects, 10.24 M
requests, 5 MB DRAM / 20 MB flash):

| Design | Miss ratio | Flash WAF | Device write (MB/s) |
|---|---|---|---|
| SA | 0.2087 | 64.0 | 430.2 |
| Kangaroo | 0.1860 | 14.5 | 86.1 |
| LS | 0.2124 | 1.0 | 6.9 |

Kangaroo Pareto-dominates SA (fewer misses *and* fewer writes) and delivers
12.4% fewer misses than LS at a higher write rate — reproducing the paper's
Fig. 8 story. Sensitivity sweeps (DRAM, flash, object size, admission
probability, RRIParoo bits, KLog size, admission threshold) are in
`results/sweeps/` and `figures/`; see [`report.md`](report.md).

## Testing

```bash
bash tests/run_golden.sh           # golden-trace regression (exact match)
bash tests/run_edge_cases.sh       # manual edge-case traces
bash scripts/build-asan.sh         # ASan/UBSan target: simulator/bin/asan/cache
bash tests/run_sanitizer.sh        # golden + edge cases under ASan/UBSan
python3 scripts/markov-threshold.py # Phase 8 threshold model comparison
```

## Roadmap

| Phase | Theme | Status |
|---|---|---|
| 0 | Toolchain + build fixes | Done |
| 1 | SA / LS baselines | Done |
| 2 | Test harness + deterministic workloads | Done |
| 3 | KLog (partitioned index + circular log) | Done |
| 4 | KSet (set-associative + Bloom filter) | Done |
| 5 | Admission policies | Done |
| 6 | RRIParoo | Done |
| 7 | Paper figure reproduction | Done |
| 8 | Correctness + sanitizers + docs | Done |
| 9 | On-flash CacheLib track | Optional (needs HW) |
| 10 | AdaKanga (adaptive admission) | Scaffolded |
| 11 | Kangaroo-TTL (expiry-aware) | Scaffolded |

## Contributing

1. Fork and create a feature branch.
2. Run `scripts/build.sh`, `bash tests/run_golden.sh`, and `bash tests/run_edge_cases.sh` before opening a PR.
3. Keep commits small and focused; follow conventional commit style
   (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).

## License

MIT. See `LICENSE`.

## Citation

If you use this work, please cite the original paper:

```bibtex
@inproceedings{mccallister2021kangaroo,
  title     = {Kangaroo: Caching Billions of Tiny Objects on Flash},
  author    = {McCallister, Alexandra and Naik, Antariksha and Michael, Nithin and
               Giannelli, Christina and Mitzenmacher, Michael and Beckmann, Becky J.},
  booktitle = {Proceedings of the ACM Symposium on Operating Systems Principles (SOSP '21)},
  year      = {2021},
  doi       = {10.1145/3477132.3483568}
}
```

Extended journal version: ACM Transactions on Storage (TOS), 2022.
