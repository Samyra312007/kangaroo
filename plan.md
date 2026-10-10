# Plan: End-to-End Implementation of *Kangaroo: Caching Billions of Tiny Objects on Flash* (SOSP '21)

> **Goal:** Reimplement, from scratch and end to end, the Kangaroo hybrid DRAM/flash cache for
> billions of tiny objects, reproduce its headline results with the reference simulator, and extend
> it with **two new features** beyond the paper.
>
> **Accuracy note:** This plan was corrected against the actual SOSP '21 paper text (local extract
> used during authoring). Terms below match the paper exactly — in particular **SA = Set-Associative
> baseline** (not "smart annealing"; the paper contains no such mechanism), and **KSet is an on-flash
> set-associative cache**, while **KLog is a small on-flash log** with an **in-DRAM** partitioned index.

---

## 0. TL;DR

| Item | Value |
|---|---|
| **Primary track (buildable here)** | The C++ **simulator** — `github.com/saramcallister/Kangaroo` |
| **Secondary track (needs real flash HW, optional)** | CacheLib on-flash fork `github.com/saramcallister/CacheLib-1` |
| **Language / build** | C++17 (g++ 13), **SCons**, Python 3, `libconfig++` |
| **Core artifact** | A working `simulator/bin/cache` that runs Kangaroo, SA, and LS from generated configs |
| **Evidence of success** | Reproduced miss-ratio / write-amplification trends + correctness tests + 2 extensions |
| **Deliverables** | Source, configs, run scripts, tests, graphs, `report.md`, reproducible runbook |

---

## 1. What we are implementing (the paper's actual design)

Kangaroo is a hierarchical DRAM/flash cache that combines a **set-associative** cache with a small
**log-structured** cache to serve very large working sets of tiny (≈100–300 B) objects. The core
insight: log-structured caches minimize flash writes but need too much DRAM for their index;
set-associative caches need almost no DRAM but write flash too much. Kangaroo uses each to cover the
other's weakness.

### The three layers

1. **DRAM cache** — tiny (**<1% of capacity**) in-memory cache in front of flash, holding the most
   recently inserted objects. Simulator: `memcache::LRU`, sized by `cache.memorySizeMB`.
2. **KLog** — a small (**≈5% of flash**) **log-structured flash cache** with an **in-DRAM index**.
   Writes are buffered in DRAM and flushed as large segments to a circular on-flash log, so KLog's
   write amplification is ≈1× and it produces large (low-dlwa) writes. KLog is the *write-efficient
   staging area* in front of KSet.
3. **KSet** — the **bulk (≈95% of flash) set-associative flash cache** (4 KB sets, matching flash
   granularity). KSet has **no DRAM index**: it hashes a key to a set (the LBA(s) on flash) and reads
   the whole set to scan for the key. To avoid pointless flash reads it keeps a **per-set Bloom
   filter in DRAM** (~10% false-positive rate), rebuilt whenever the set is written.

> **Lookup path:** DRAM cache → KLog (via its DRAM index) → KSet (hash key → set → Bloom filter → read
> set from flash and scan).
> **Insert path:** DRAM cache → *pre-flash admission* → KLog (index + buffered segment write) → on KLog
> eviction, *threshold admission* → KSet (move **all** KLog objects mapping to the same set together).

### The three techniques that make it work

1. **Partitioned index for KLog.** KLog's index is a hash table with separate chaining; each entry =
   {offset, tag (partial hash), next-pointer, eviction metadata, valid bit}. It is split into **64
   partitions × 2²⁰ tables** so that each index table effectively shares 20 bits of key information.
   This shrinks per-object metadata from a naïve **190 b → 48 b**, while keeping KLog's index only
   ≈2.4 b/object overall (KLog holds just ~5% of objects).
   **Enumerate-Set(x)** — return every KLog object mapping to the same KSet set as `x` — is cheap
   because, by construction, all such objects live in **the same index bucket**.
2. **Threshold admission (KLog → KSet).** Because KSet is set-associative, admitting one small object
   rewrites a whole set. Kangaroo therefore only admits a group to KSet when **≥ n objects** (default
   **n = 2**) map to the same set, amortizing the set write and reducing application-level write
   amplification (alwa) by ≥ n×. Objects that got a **hit while in KLog are readmitted** to KLog's
   head so popular objects are not lost.
3. **RRIParoo (usage-based eviction with no DRAM index).** A version of **RRIP** that stores the 3-bit
   reuse predictions **on flash** and keeps only **≈1 DRAM bit per object** (a hit bit), deferring
   all prediction updates to eviction time (when the set is rewritten anyway). This gives RRIP-quality
   hit ratio at **1 b/object instead of 3 b** — and degrades gracefully to FIFO if fewer bits are
   available. Kangaroo also uses RRIP to order KLog→KSet merges (objects enter KLog at *long* and
   decrement toward *near* on hits; KSet fills sets in near→far order).

### DRAM budget (paper, Table 1 — 2 TB cache, 200 B objects)

| Component | Naïve Log-Only | Naïve Kangaroo | **Kangaroo** |
|---|---|---|---|
| KLog index | 190 b/obj | 177 b/obj | **48 b/obj** |
| KSet (Bloom + RRIParoo) | 0 | 8 b/obj | **4 b/obj** |
| Index buckets | ~3.1 b | ~3.1 b | **~0.8 b** |
| **Total** | **193.1 b** | 19.6 b | **7.0 b/obj** |

Kangaroo's ≈7.0 b/object is **4.3× less than the previous SOTA (Flashield, 30 b/object)** and is the
number our implementation must reproduce.

### Theoretical component

The paper includes a **Markov model** (Appendix A) proving that Kangaroo reduces alwa vs. a set-only
design with **no increase in miss ratio** (Theorem 1). We treat reproducing the model as optional
(Phase 8) but will validate the simulated alwa against it.

### Default parameters (paper, Table 2)

| Parameter | Value |
|---|---|
| Total cache capacity | 93% of flash |
| Log size | 5% of flash |
| Admission probability to log from DRAM | 90% |
| Admission threshold to sets from log | 2 |
| Set size | 4 KB |

### Metrics (as defined by the paper)

- **Miss ratio** — primary metric; fraction of requests served from the backend.
- **alwa** — *application-level* write amplification (`bytes written to flash / bytes of admitted data`).
- **dlwa** — *device-level* write amplification (estimated in simulation via a best-fit exponential
  curve to 4 KB random-write dlwa; assumed 1× for LS).
- **Throughput / latency** — reported for the on-flash (CacheLib) implementation.

### The two baselines we must also build

| Baseline | What it is | Simulator mapping |
|---|---|---|
| **SA** (Set-Associative) | CacheLib's small-object cache: set-associative, **no log**, FIFO eviction; limited by high write rate (uses ≤81% of flash capacity). | `set_only_cache.*` (`memoryCache` + `sets`) |
| **LS** (Log-Structured) | Optimistic log-structured cache with a **full DRAM index** and FIFO eviction; limited by DRAM index reach (~61% of device capacity). | `mem_log_cache.*` (`memoryCache` + `log`) |

**Reference result to reproduce:** on the Facebook trace with 16 GB DRAM, a 1.9 TB drive and writes
< 62.5 MB/s, Kangaroo reduces misses by **29% vs. SA** and **56% vs. LS**, and lowers miss ratio from
**0.29 → 0.20**.

---

## 2. Definition of Done / Acceptance Criteria

- [ ] `scons` builds `simulator/bin/cache` from a clean tree with **zero errors**.
- [ ] One config per design (`kangaroo`, `sa`, `ls`) runs to completion and emits stats.
- [ ] Kangaroo reproduces the paper's *directional* results at matched DRAM: **lowest miss ratio** of
      the three, **alwa ≪ SA**, and DRAM usage near LS.
- [ ] Main-result figures reproduced: **Fig. 7** (miss ratio over a 7-day trace) and **Fig. 8**
      (Pareto: miss ratio vs. device write rate).
- [ ] Sensitivity figures reproduced: **Fig. 9** (DRAM), **Fig. 10** (flash capacity), **Fig. 11**
      (avg object size), and the **§5.4 technique sweeps Fig. 12 a–d** (pre-flash admission probability,
      RRIParoo bits, KLog size %, KSet threshold).
- [ ] **Table 1** (DRAM bits/object), **Table 2** (default parameters), and the **Appendix B / Table 4**
      scaling methodology all implemented/reproduced. Reported **DRAM ≈ 7.0 bits/object** for Kangaroo on
      the 2 TB / 200 B-object parameterization.
- [ ] Correctness suite passes: hit/miss accounting, capacity invariants, Bloom-filter false-positive
      bound, RRIParoo promotion semantics, threshold-admission collision counting, alwa accounting.
- [ ] **Extension 1** and **Extension 2** implemented, benchmarked, and shown to improve on their
      respective baselines.
- [ ] `report.md` cites the paper + journal version and documents reproduced vs. reported numbers.
- [ ] Fresh-machine reproduction via `scripts/run-all.sh`.

---

## 3. Reference Repository Layout (what we build on)

```
Kangaroo/
├── simulator/                 # C++ core — the material we implement against
│   ├── main.cpp               # entry: parse config -> build Cache -> stream requests
│   ├── SConstruct/SConscript  # SCons build
│   ├── config.hpp             # libconfig reader (ConfigReader, dotted keys)
│   ├── constants.hpp          # INDEX_LOG_RATIO=0.02, MIN_FLASH_WRITE_BYTES=4096, HIT_BIT_VECTOR_SIZE=32
│   ├── bytes.hpp, candidate.hpp, mem_cache.hpp, lru.hpp, rand.hpp
│   ├── caches/
│   │   ├── cache.{hpp,cpp}         # abstract Cache + factory dispatch
│   │   ├── mem_log_sets_cache.*    # <-- KANGAROO (memCache + log + sets)
│   │   ├── set_only_cache.*        # <-- SA baseline (memCache + sets)
│   │   ├── mem_log_cache.*         # <-- LS baseline (memCache + log)
│   │   └── mem_only_cache.*
│   ├── sets.{hpp,cpp}, sets_abstract.hpp   # <-- KSet (set-associative)
│   ├── rrip_sets.{hpp,cpp}                 # <-- RRIParoo in KSet
│   ├── log_abstract.hpp, rotating_log.{hpp,cpp}, log.{hpp,cpp}, log_only.*, log_simple.*  # <-- KLog
│   ├── admission/  admission.*, threshold.hpp, random_admission.hpp   # pre-flash + threshold admission
│   ├── parsers/    parser.*, zipf_parser.hpp, facebook_tao_parser_simple.hpp
│   ├── stats/      stats.{hpp,cpp}
│   └── lib/        csv.h, json.hpp, zipf.h
├── run-scripts/  genConfigs.py, config.py, runLocal.py, template.cfg
└── graph-scripts/  dram_perc_vs_mr.py, flash_cap_vs_mr.py, obj_sizes_vs_mr.py, wr_vs_mr.py,
                     miss_ratio_kangaroo_params.py, threshold_model.py, parameters.py
```

### Key interfaces we must honor

| Interface | Contract |
|---|---|
| `cache::Cache` | Pure virtual `insert(candidate_t)`, `find(candidate_t)`, `calcFlashWriteAmp()`; base `access()` does hit/miss accounting then calls `insert` on a miss. |
| `Cache::create(setting)` | Factory: picks a concrete cache from presence of `memoryCache` / `log` / `sets` sections. **This selects Kangaroo vs SA vs LS.** |
| `flashCache::SetsAbstract` | `insert(batch)`, `insert(set_num, batch)`, `find`, `findSetNums`, `ratioCapacityUsed`, `calcWriteAmp`, `calcMemoryConsumption`, `trackHit`. → **KSet**. |
| `flashCache::LogAbstract` | `insert(batch)`, `insertFromSets`, `find`, `readmit`, `ratioCapacityUsed`, `calcWriteAmp`. → **KLog**. |
| `memcache::MemCache` | `insert(candidate_t)` (returns evictions), `find`, `flushStats`. → **DRAM cache**. |
| `admission::Policy` | `admit(items) -> {set_num: [items]}`, `admit_simple`, `byteRatioAdmitted()`. Used **twice**: `preLogAdmission` (DRAM→KLog) and `preSetAdmission` (KLog→KSet). |
| `misc::ConfigReader` | Dotted-key typed reads with defaults. |
| `parser::Parser` | `create(root)` + `go(callback)`; new trace formats = new `Parser` subclass. |

**Insert flow (from `MemLogSetsCache::insert`):**
`memCache->insert(id)` → `prelog_admission->admit(...)` → `log->insert(...)` → if the log returns
evictions → `preset_admission->admit(...)` → `sets->insert(set_num, items)`.
**Find flow:** `memCache->find(id) || log->find(id) || sets->find(id)`.

---

## 4. Environment Prerequisites

**Verified on this machine:** Ubuntu 24.04, g++ 13.3, Python 3.12, 36 cores, 62 GB RAM.
**Missing and required:**

```bash
sudo apt-get update
sudo apt-get install -y scons libconfig++-dev
pip install SCons          # fallback if apt scons is unavailable
```

Notes / gotchas:
- The **README build steps are partially broken** — the corrected steps above are authoritative.
- g++ 13 may warn/error on the older codebase — set `-std=c++17`, and fix real issues (do not
  blanket-silence warnings).
- The paper's numbers come from 2×16-core Xeon E5-2698 / Ubuntu 18.04 / 64–128 GB DRAM / WD SN840
  1.92 TB (3 DWPD → 62.5 MB/s). Our sweeps emulate those *constraints* in simulation, not the HW.
- The on-flash track (Phase 9) needs a raw flash block device and is **optional here**.

**Phase 0 checklist**
- [ ] Toolchain installed (`scons`, `libconfig++-dev`, `python3`, `g++`).
- [ ] Repo cloned into `third_party/Kangaroo` (pristine reference); working tree at repo root.
- [ ] `scons` produces `simulator/bin/cache`; runs a sample config without crashing.
- [ ] Decision recorded: adopt upstream simulator as our base vs. clean-room reimplementation.
- [ ] Tag `phase-0-bringup`.

---

## 5. Phase-Wise Implementation Plan

Each phase: **Tasks → Deliverable → Verification**. Do not advance on an unverified phase.

### Phase 1 — Baselines bring-up (SA + LS)
**Tasks**
1. Generate and run baseline configs:
   ```bash
   cd run-scripts
   ./genConfigs.py sa-zipf --zipf 0.9 --mem-size-MB 5 --flash-size-MB 20 --pre-set-random .8 .9 1
   ./genConfigs.py ls-zipf --zipf 0.9 --mem-size-MB 5 --flash-size-MB 20 --pre-log-random .8 .9 1 --no-sets
   ./runLocal.py configs --jobs 3
   ```
2. Record miss ratio and alwa for SA and LS across DRAM {1,2,3,5,10} MB and flash {10,20,50} MB.
3. Log which concrete cache `Cache::create` selected so we know each path is really exercised.

**Deliverable:** `results/baselines/*.csv`, `phase1.md`.
**Verification:** Baselines complete; miss ratio decreases monotonically with cache budget; LS alwa ≈ 1
(log-structured); SA alwa ≫ 1 (set rewrite); `totalAccesses = hits + misses`.

### Phase 2 — Test harness + deterministic workloads
**Tasks**
1. Pin the RNG seed in `rand.hpp` for reproducibility.
2. Add a **golden trace** with hand-computed miss ratio.
3. Add `scripts/run-all.sh` (generate → run → collect) and `scripts/collect.py` (config+stats → CSV).
4. Sanity-check the Zipf parser's key distribution; add a Facebook/Twitter-like trace parser if needed
   (subclass `Parser`, register in `parser.cpp`).

**Deliverable:** `tests/` runner, golden fixture, collector, trace parser.
**Verification:** Golden trace reproduces expected counts exactly; two identical runs → byte-identical stats.

### Phase 3 — KLog: partitioned index + circular log
**Tasks**
1. Implement the KLog index as a **hash table with separate chaining**: entry = {offset, tag,
   next-pointer, eviction metadata, valid bit}.
2. **Partition** it into 64 partitions × 2²⁰ tables; shrink offset / tag / next-pointer sizes so
   per-object metadata approaches the paper's **48 b/object** (assert against Table 1).
3. Implement the **circular on-flash log** with segment-sized buffered writes
   (`log.flushBlockSizeKB` → `RotatingLog`); keep one segment free; flush in FIFO order.
4. Implement **Enumerate-Set(x)** — iterate the bucket for `x`'s KSet set.
5. `calcWriteAmp()` for KLog (alwa ≈ 1×), plus dlwa contribution (large sequential writes).

**Deliverable:** `LogAbstract` implementation with working Enumerate-Set.
**Verification:** Unit test — all objects mapping to a set are found by Enumerate-Set; no live object
lost across ≥ 2× capacity turnover; alwa ≈ 1; metadata/bits-per-object asserted against Table 1.

### Phase 4 — KSet: set-associative flash cache + Bloom filter
**Tasks**
1. Implement `sets.{hpp,cpp}` as `SetsAbstract`: fixed 4 KB sets, hash key → set, read-set-and-scan
   lookup, no DRAM index.
2. Implement the **per-set Bloom filter** (~10% FP target), rebuilt on every set write.
3. Implement multihash placement (`findSetNums`, `numHashFunctions`) to raise set occupancy.
4. Track DRAM cost: Bloom + eviction metadata ≈ **4 b/object** (Table 1).

**Deliverable:** KSet functional with Bloom filter.
**Verification:** Measured Bloom FP rate within target; set occupancy/capacity invariants hold; DRAM
bits/object for KSet matches the paper's order.

### Phase 5 — DRAM cache + admission policies
**Tasks**
1. `memcache::LRU` sized as `memorySizeMB − (log capacity × index overhead) − sets memory`, per
   `MemLogSetsCache` (`INDEX_LOG_RATIO = 0.02`).
2. **Pre-flash admission** (`random_admission.hpp`): admit DRAM evictions to KLog with probability `p`
   (default **90%**); must be zero-DRAM-overhead.
3. **Threshold admission** (`threshold.hpp`): group KLog evictions by target KSet set and admit a group
   only when `|group| ≥ n` (default **n = 2**); otherwise drop.
4. **Readmission**: objects that received a hit while in KLog go back to the head of the log.
5. Make both policies config-selectable (`preLogAdmission`, `preSetAdmission`).

**Deliverable:** Full admission chain; `--multiple-admission-policies` works.
**Verification:** As `n` rises, admission fraction falls and alwa falls (reproduce Fig. 5 trend);
`byteRatioAdmitted()` shrink the alwa correctly in `calcFlashWriteAmp()`.

### Phase 6 — RRIParoo eviction
**Tasks**
1. Implement RRIP with 3-bit reuse predictions (near `000` → far `111`); new objects inserted at `long`
   (`110`); promote to `near` on hit; evict at `far`; on no-far, increment all predictions.
2. Store predictions **on flash**; keep only a **1-bit-per-object hit vector** in DRAM
   (`HIT_BIT_VECTOR_SIZE = 32`); defer promotions/increments to eviction-time set rewrite.
3. Wire RRIP into the **KLog→KSet merge** so sets fill near→far, breaking ties toward objects already
   in KSet. Implement `rrip_sets.{hpp,cpp}` (bits, promotion-only, mixed RRIP variants).

**Deliverable:** `RripSets` with correct promotion/merge semantics.
**Verification:** Eviction never writes metadata beyond the one set rewrite per flush; a controlled
trace shows RRIParoo retains a frequently-hit object that FIFO evicts; DRAM overhead ≈ 1 b/object.

### Phase 7 — Full evaluation & paper reproduction
**Tasks**
1. Reproduce the main result: **Fig. 7** (miss ratio over a 7-day Facebook trace) and **Fig. 8**
   (Pareto curve of miss ratio vs. device write rate; ≤16 GB DRAM, 2 TB flash).
2. Sweep the four constraint axes and reproduce the sensitivity figures: **Fig. 8** (device write
   budget), **Fig. 9** (DRAM 5→64 GB), **Fig. 10** (flash device capacity), **Fig. 11** (avg object
   size, kept at constant working set).
3. Reproduce the **§5.4 parameter-sensitivity / benefit attribution (Fig. 12 a–d)**: (a) pre-flash
   admission probability 10–100%, (b) FIFO vs RRIParoo with 1–4 bits, (c) KLog size % of flash,
   (d) KSet admission threshold. Check against the paper's numbers: threshold n=2 → −32.0% write rate /
   +6.9% misses; KLog → −42.6% writes; RRIParoo (3-bit) → −8.4% misses; pre-flash admission → −8.2%
   writes; RRIParoo 1-bit → 3.4% / 3-bit → 8.4% fewer misses vs FIFO.
4. Implement the **Appendix B scaling methodology (Table 4)** so sampled traces are scaled to a
   full-server equivalent — required for the object-size sweep at constant working set.
5. Build the DRAM bits/object table (**Table 1**) from our implementation's own accounting.
6. Compare vs. SA and LS at matched DRAM; document reproduced vs. reported values.

**Deliverable:** `results/` CSVs, `figures/*.pdf` (Figs 7–12), reproduction table in `report.md`.
**Verification:** Directional claims match the paper (Kangaroo lowest miss ratio; 29% vs SA / 56% vs LS
reproduced as trends); deviations explained (trace sampling, simulator approximations).

### Phase 8 — Theory check, correctness, docs
**Tasks**
1. *(Optional)* Implement the **Markov model (Appendix A, Table 3)** and compare its predicted alwa
   (Theorem 1) to simulation.
2. Consolidate unit/integration tests; add edge cases (empty trace, all-miss/all-hit, 0-byte objects,
   n=1 threshold, single-segment log, over-capacity, duplicate keys).
3. Add ASan/UBSan build target; run the golden trace under it.
4. Write `report.md` (design ↔ paper mapping, results, deviations) and finish the runbook.

**Deliverable:** Green tests, sanitizer-clean run, report, reproducible runbook.
**Verification:** `scripts/run-all.sh` passes from a clean checkout; no leaks/UB.

### Phase 9 — On-flash CacheLib track + §5.5 production test
**Tasks**
1. Clone `CacheLib-1`; checkout `artifact-eval-kangaroo-upstream` (Kangaroo + SA) and
   `artifact-eval-log-only-upstream` (LS).
2. `./contrib/build.sh -j -v -d`; run `cachebench` with configs from
   `cachelib/cachebench/test_configs/kangaroo`; tune #KLog partitions, threshold, KLog size.
3. Collect cachebench stats (hit ratio, r/w latency, throughput, alwa/dlwa).
4. *(Out of scope — documented as non-reproducible)* **§5.5 / Fig. 13**, the production test deployment
   at Meta (dark launch). Reported outcomes: **18% fewer misses** at equivalent write rate, **38% less
   write** when both admit all, and **42.5% less write** with the **ML pre-flash admission policy**.
   This needs Meta production infrastructure and the private traces, so we replicate only the
   *simulation-side* comparison of probabilistic vs. ML pre-flash admission and record the §5.5 result
   as an explicit limitation.

**Verification:** Needs a raw flash block device — **skip with a documented limitation if no HW**.

---
### Phase 10 Adaptive Admission & Partitioning (`AdaKanga`)
**Motivation.** The paper's admission probability, threshold, KLog size, and partition count are
chosen statically. Real workloads shift (changing hot set, object-size mix, write budget). We add an
**online controller** that adapts these knobs to minimize miss ratio subject to a **write-rate ceiling**.

**Design**
- New `simulator/admission/adaptive.hpp` implementing `admission::Policy`, plus a controller in
  `MemLogSetsCache` that jointly adapts:
  1. **pre-flash admission probability `p`** (DRAM→KLog),
  2. **threshold `n`** (KLog→KSet),
  3. **KLog size %** and optionally **#partitions**.
- Objective: minimize miss ratio s.t. alwa·write-rate ≤ a configured ceiling. Use a **sliding-window
  marginal-benefit estimator** over recent accesses (bandit/PID-style update **with hysteresis** to
  avoid oscillation).
- Add a **workload-shift trace generator** (hot set and object-size mix move in phases) to exercise it.

**Deliverable:** `adaptive.hpp` + controller + shift workload + comparison vs. fixed (p=90%, n=2) and
vs. the paper's defaults.
**Verification / success criteria**
- On the static reference workload: **within 2% miss ratio of the best fixed configuration**, found
  without being told it.
- On the shift workload: **strictly lower miss ratio than any single fixed config**.
- Steady-state control noise bounded (no unbounded oscillation); write rate never exceeds the ceiling.

### Phase 11 TTL / Expiry-Aware Kangaroo (`Kangaroo-TTL`)
**Motivation.** Production caches have **per-object TTLs**; log-structured flash cannot delete in
place, so expiry either leaks flash or forces cleaning. The paper does not model expiry.

**Design**
- Extend `parser::Request` / `candidate_t` with an optional **expire-time**; extend the Zipf parser
  and add a **churn workload** (long-lived + short-lived objects).
- **Lazy invalidation**: carry a compact timestamp/epoch with each KLog index entry and KSet Bloom
  filter bit; expired entries count as misses; **KLog segment flushing drops expired records instead
  of rewriting them** (the main alwa win).
- **Short-TTL fast path**: objects with TTL below an expected-residency cutoff are **not admitted to
  flash** (or admitted with a tiny probability) — integrates with Extension 1's controller, which can
  learn the cutoff.

**Deliverable:** TTL plumbing end-to-end + churn workload + expiry-aware cleaning.
**Verification / success criteria**
- Correctness: an object past its TTL is **never** returned as a hit (asserted in tests).
- On a churn workload with X% short-TTL traffic: **alwa decreases** vs. vanilla Kangaroo, and miss
  ratio on long-lived objects does not regress beyond a small bound.
- Expanded records reduce live-bytes-on-flash growth relative to vanilla.

### (Stretch / backlog — not committed)
- Real public trace parser (Facebook/Twitter-style) to validate both extensions.
- Per-tenant fair DRAM/flash sharding; object compression on flash; direct dlwa device modeling.

---

## 7. Milestones & Timeline (indicative, solo-dev)

| Milestone | Phases | Est. |
|---|---|---|
| M1 — Toolchain + SA/LS baselines green | 0–1 | 3 days |
| M2 — Test harness + golden trace | 2 | 2 days |
| M3 — KLog (partitioned index + Enumerate-Set) | 3 | 4 days |
| M4 — KSet + Bloom filter | 4 | 3 days |
| M5 — DRAM cache + admission + RRIParoo (Kangaroo runnable) | 5–6 | 5 days |
| M6 — Paper figures reproduced | 7 | 4 days |
| M7 — Extensions 1 & 2 implemented + measured | 10–11 | 6 days |
| M8 — Theory check, tests, docs, (optional) CacheLib | 8–9 | 3 days |

---

## 8. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Old C++ codebase vs. g++ 13 | Build failures | `-std=c++17`; fix root causes, not blanket suppression |
| README build steps broken | Wasted time | Use the corrected runbook (§4) |
| Simulator's dlwa is estimated, not measured | Reproduction mismatch | Report **alwa** from simulation; document the dlwa estimate; Track B for real dlwa |
| No flash device for Track B | Can't run on-flash | Mark Track B optional; simulator is the complete primary deliverable |
| Adaptive controller oscillates | Unstable results | Hysteresis + convergence test in Phase 10 criteria |
| Coverage drift from the paper | Wrong system | Phases 3–6 each assert a specific paper table/figure |
| Extension scope creep | Slipped schedule | Extensions have explicit criteria; backlog deferred |

---

## 9. Reproducibility Checklist (per published result)

- [ ] Config committed under `configs/` with all non-default parameters.
- [ ] RNG seed pinned; trace source and sampling recorded.
- [ ] Raw stats committed under `results/` (or regenerable by `scripts/run-all.sh`).
- [ ] Graph produced by the committed `graph-scripts/` entry point, not by hand.
- [ ] Toolchain noted (this box: Ubuntu 24.04, g++ 13.3).
- [ ] Citation attached to each reproduced figure: SOSP '21 (`10.1145/3477132.3483568`) and ToS '22.

---

## 10. References

1. **Paper (author-hosted PDF, primary source)** — http://cs.cmu.edu/~beckmann/publications/papers/2021.sosp.kangaroo.pdf
2. **ACM DL (SOSP '21)** — https://dl.acm.org/doi/10.1145/3477132.3483568
3. **Extended journal version (ACM ToS '22, open PDF)** — http://cs.cmu.edu/~beckmann/publications/papers/2022.tos.kangaroo.pdf
4. **Simulator repo (core material)** — https://github.com/saramcallister/Kangaroo
5. **On-flash CacheLib fork (optional Track B)** — https://github.com/saramcallister/CacheLib-1
6. **Artifact review summary + corrected build steps** — https://sysartifacts.github.io/sosp2021/summaries/kangaroo
7. **Conference talk (40 min)** — https://www.youtube.com/watch?v=d1dFmF3IJOI
8. **Meta engineering blog (accessible intro)** — https://engineering.fb.com/2021/10/26/core-infra/kangaroo/

---

## 11. Immediate Next Actions

1. `sudo apt-get install -y scons libconfig++-dev`; clone the simulator into `third_party/Kangaroo`.
2. Build `simulator/bin/cache`; run every sample config from the README to confirm all paths.
3. Generate SA + LS baseline configs and collect the first miss-ratio/alwa table (**Phase 1**).

---

## 12. Paper Coverage Matrix (baseline completeness)

Every section, figure, and table of the SOSP '21 paper, and where this plan covers it.

| Paper element | Content | Covered in |
|---|---|---|
| §1 Introduction | Problem, key idea, contributions | §1 |
| §2 Background / Related Work (**Fig. 2**) | alwa vs dlwa, why prior designs fail | §1 "Metrics", §8 risks |
| §3 Overview & Motivation (**Fig. 3**) | DRAM cache + KLog + KSet; lookup/insert; Theorem 1 | §1 "three layers" |
| §4.1 Pre-flash admission to KLog | Random admission probability `p` | Phase 5 |
| §4.2 KLog (**Fig. 4**) | Partitioned chained index, lookup/insert, **Enumerate-Set**, 48 b/obj | Phase 3 |
| §4.3 KLog → KSet (**Fig. 5**) | Threshold admission (≥ n collisions), readmission | Phase 5 |
| §4.4 KSet (**Fig. 6**) | Per-set Bloom filter, **RRIParoo** (1 b/obj), KLog→KSet merge order | Phase 4, 6 |
| **Table 1** | DRAM bits/object breakdown (7.0 b/obj) | §1, Phases 4, 7 |
| **Table 2** | Default parameters (93%, 5%, p=90%, n=2, 4 KB) | §1 |
| §5.1 Experimental setup | CacheLib impl, HW, traces, dlwa estimate, **Appendix B scaling** | §4, Phases 1–2, 7 |
| §5.2 Main result (**Fig. 7, Fig. 8**) | Miss ratio over time; Pareto vs write rate | Phase 7 |
| §5.3 Constraints (**Fig. 9, 10, 11**) | DRAM, flash capacity, avg object size | Phase 7 |
| §5.4 Techniques (**Fig. 12 a–d**) | Admission prob, RRIParoo bits, KLog size, threshold; benefit attribution | Phase 7 |
| §5.5 Production test (**Fig. 13**) | Meta dark launch; ML admission; 18%/38%/42.5% | Phase 9 (documented non-reproducible) |
| §6 Conclusion | — | — |
| **Appendix A** (**Table 3**) | Simplified Markov model, Theorem 1 | Phase 8 |
| **Appendix B** (**Table 4**) | Scaling methodology for experiments | Phase 7 |
| Baselines **SA / LS** | Set-associative (FIFO) / log-structured (full DRAM index) | §1, Phase 1 |

**Verdict:** all design components (§3, §4), both baselines, all four evaluation extractions
(§5.2–5.4), Tables 1–2, and both appendices are covered. The only paper result not reproducible is the
§5.5 production deployment, which is explicitly flagged as out of scope.
