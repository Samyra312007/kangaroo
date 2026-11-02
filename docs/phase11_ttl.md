# Phase 11: Kangaroo-TTL expiry-aware caching

Phase 11 adds TTL-aware object expiry to the Kangaroo simulator and evaluates a
Kangaroo-TTL policy that avoids wasting flash writes on short-lived objects.

The simulator already supports log and set admission. Phase 11 adds expiration
semantics, expired-hit accounting, short-TTL admission rejection, and a
deterministic workload that separates short-lived churn from long-lived objects.

## TTL semantics

A request tuple is parsed as:

```text
id, size, oracle_count, expire_time
```

An object is treated as expired when:

```text
expire_time != 0 && current_time >= expire_time
```

Expired objects never count as hits. If an expired object is found in the DRAM
cache, KLog, or KSet, the simulator drops it and records an expired miss.

The validator checks expired misses separately from ordinary misses so that the
cache does not silently count expired objects as successful lookups.

## Expired objects in cache layers

When an expired object reaches any cache layer:

- the DRAM cache removes it before lookup;
- KLog insertion skips expired stores;
- KLog flushing drops expired records instead of writing them to flash;
- KSet insertion skips expired stores;
- KSet lookup drops expired objects.

This keeps flash occupancy focused on objects that can still serve future hits.

## Adaptive short-TTL admission

The Phase 11 Adaptive policy rejects short-TTL objects before they enter flash:

```text
remainingTtl <= shortTtl
```

This prevents short-lived objects from being admitted to KLog or KSet unless
they have enough remaining lifetime to justify a flash write.

The relevant config knob is:

```cfg
preLogAdmission = {
  policy = "Adaptive";
  shortTtl = 1000;
};
```

`shortTtl = 0` disables the short-TTL rejection rule and acts as the TTL-only
baseline.

## Workload

`scripts/generate_phase11_workload.py` creates four trace families:

| Trace family | Purpose |
|---|---|
| Mixed short/long TTL | Measures short-TTL write suppression while keeping long objects stable |
| Vanilla no-expiry | Baseline that allows normal flash writes |
| Long-only | Checks that TTL admission does not regress long-lived workloads |
| Long TTL only | Checks that long expiry does not degrade steady-state hits |

The workload is deterministic and uses manual request tuples, so Phase 11 results
can be reproduced without random trace generation.

## Generated configs

```bash
python3 scripts/generate_phase11_workload.py
```

This writes configs under:

```text
configs/phase11/
```

The main configs are:

| Config | Policy | Meaning |
|---|---|---|
| `vanilla.cfg` | Random admission, no expiry | Baseline Kangaroo without TTL rejection |
| `ttl.cfg` | Adaptive with short-TTL rejection | Kangaroo-TTL short-lived object suppression |
| `ttl_no_short.cfg` | Adaptive with TTL expiry only | Expired objects are skipped, but short TTL is not rejected |
| `long_only_vanilla.cfg` | Random admission, no expiry | Long-object baseline |
| `long_only_ttl.cfg` | Adaptive, long object no expiry | Long-object stability check |
| `long_ttl_ttl.cfg` | Adaptive, long TTL | Long TTL stability check |
| `long_ttl_vanilla.cfg` | Random admission, long TTL | Long TTL baseline |

## Validation

Run:

```bash
bash scripts/build.sh
python3 scripts/generate_phase11_workload.py
python3 scripts/validate_phase11.py
```

The validator writes:

```text
results/phase11/summary.json
```

and reports the following criteria:

```json
{
  "expiredObjectsAreNeverHits": true,
  "shortTtlAdmissionRejected": true,
  "shortTtlFlashWritesReducedVsVanilla": true,
  "shortTtlFlashWriteAmpReducedVsVanilla": true,
  "liveFlashBytesReducedVsVanilla": true,
  "longOnlyMissNoRegression": true,
  "longTtlMissNoRegression": true
}
```

At the current Phase 11 settings:

| Config | Miss rate | Flash write amp | Flash bytes written | Live flash bytes | Short-TTL rejects | Expired misses |
|---|---:|---:|---:|---:|---:|---:|
| `vanilla.cfg` | 0.103247 | 0.909236 | 4,677,632 | 4,677,632 | 0 | 0 |
| `ttl.cfg` | 0.849376 | 0.000000 | 0 | 0 | 1,000 | 9,000 |
| `ttl_no_short.cfg` | 0.849376 | 0.052873 | 4,153,344 | 4,153,344 | 0 | 9,000 |

The long-only and long-TTL checks show a relative miss-rate delta of `0.000`,
meaning Phase 11 does not regress long-lived object behavior.

## Current result

Phase 11 passes its intended correctness and performance criteria:

- expired objects never count as hits;
- short-TTL objects are rejected before flash admission;
- Kangaroo-TTL writes fewer flash bytes than the vanilla baseline;
- Kangaroo-TTL flash write amplification is lower than the vanilla baseline;
- live flash bytes are reduced relative to the vanilla baseline;
- long-lived workloads do not regress.

## Limitations

The current Phase 11 evaluation uses a small deterministic workload. It proves
the mechanism, but it does not yet measure billions of objects at production
scale. Future work should extend Phase 11 to large synthetic traces and compare
Kangaroo-TTL against CacheLib or production flash caches under realistic TTL
distributions.
