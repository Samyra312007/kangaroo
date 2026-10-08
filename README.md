# Kangaroo — end-to-end implementation

Working implementation of **Kangaroo: Caching Billions of Tiny Objects on Flash**
(SOSP '21), plus two planned extensions. The phase-by-phase plan lives in
[`plan.md`](plan.md).

This repository builds and drives the reference **simulator** from the paper's
artifact. Baselines **SA** (set-associative) and **LS** (log-structured) are
exercised here; Kangaroo itself is implemented in later phases.

## Layout

```
plan.md                     phase-wise implementation plan
configs/baselines/          generated SA / LS simulator configurations (Phase 1)
results/baselines/          baseline logs + collected CSV (Phase 1)
scripts/
  setup-deps.sh             build SCons + libconfig++ into .deps/ (no root)
  build.sh                  build third_party/Kangaroo/simulator/bin/cache
  run-baselines.sh          run all baseline configs, capture stdout
  collect.py                parse logs -> results/baselines/baseline_results.csv
third_party/Kangaroo/       vendored upstream simulator (see build fixes below)
docs/phase1.md              Phase 0/1 notes, build fixes, results
```

## Requirements

Linux with `g++` (C++14+), `python3`, `curl`, `make`, and network access.
No root required — dependencies are built into `.deps/`.

## Build

```bash
scripts/setup-deps.sh     # SCons (venv) + libconfig++ (from source)
scripts/build.sh          # -> third_party/Kangaroo/simulator/bin/cache
```

## Run the Phase 1 baselines

```bash
scripts/run-baselines.sh 8      # 8 parallel jobs
python3 scripts/collect.py      # -> results/baselines/baseline_results.csv
```

## Build fixes applied to the vendored simulator

The upstream README's build steps do not work as-is (consistent with the SOSP
artifact review). The vendored copy under `third_party/Kangaroo` carries three
minimal, documented fixes:

1. `simulator/lib/SConscript` — added. Upstream `SConscript` references this
   file but it does not exist in the repo; `lib/` is headers-only.
2. `simulator/SConstruct` — locates libconfig++ via `LIBCFG_INCLUDE` /
   `LIBCFG_LIB`, and force-includes `<cstdint>` (legacy sources rely on a
   transitive include that modern g++ no longer provides).
3. Binary is linked with an rpath to the project-local libconfig++, so no
   `LD_LIBRARY_PATH` is needed at run time.
