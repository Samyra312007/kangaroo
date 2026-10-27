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
  into CSV.
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
assets/logo.svg             project logo
configs/baselines/          generated SA / LS simulator configurations (Phase 1)
configs/golden/             golden regression config
results/baselines/          baseline logs + collected CSV (Phase 1)
results/golden/             golden expected output
scripts/
  setup-deps.sh             build SCons + libconfig++ into .deps/ (no root)
  build.sh                  build third_party/Kangaroo/simulator/bin/cache
  build-asan.sh             sanitizer build (Phase 8)
  run-baselines.sh          run all baseline configs, capture stdout
  run-all.sh                one-command full reproduction
  collect.py                parse logs -> results/baselines/baseline_results.csv
tests/
  run_golden.sh             golden-trace regression test
  golden.expected           committed expected steady-state line
third_party/Kangaroo/       vendored upstream simulator (with build fixes)
docs/
  phase1.md                 Phase 0/1 notes, build fixes, results
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

## Testing

```bash
bash tests/run_golden.sh   # golden-trace regression (exact match)
```

## Roadmap

| Phase | Theme | Status |
|---|---|---|
| 0 | Toolchain + build fixes | Done |
| 1 | SA / LS baselines | Done |
| 2 | Test harness + deterministic workloads | Done |
| 3 | KLog (partitioned index + circular log) | Done |
| 4 | KSet (set-associative + Bloom filter) | Done |
| 5-6 | Admission, RRIParoo | Vendored simulator provides reference; verification pending |
| 7 | Paper figure reproduction | Planned |
| 8 | Correctness + sanitizers + docs | Planned |
| 9 | On-flash CacheLib track | Optional (needs HW) |
| 10 | AdaKanga (adaptive admission) | Scaffolded |
| 11 | Kangaroo-TTL (expiry-aware) | Scaffolded |

## Contributing

1. Fork and create a feature branch.
2. Run `scripts/build.sh` and `bash tests/run_golden.sh` before opening a PR.
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
