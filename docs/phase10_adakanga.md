# Phase 10: AdaKanga adaptive admission

Phase 10 adds an adaptive admission controller called `AdaKanga` to the Kangaroo simulator. The controller adapts admission and KLog capacity during a trace instead of relying on one static policy setting.

## Controller parameters

AdaKanga tunes:

- `admitRatio`: admission probability.
- `setThreshold`: candidate group threshold.
- `minAdmitHits`: minimum number of accesses before an object can be admitted.
- `startLogFraction`, `minLogFraction`, `maxLogFraction`: dynamic KLog capacity fraction.
- `partitions`, `minPartitions`, `maxPartitions`: dynamic KLog partition count.
- `interval`: controller interval in accesses.
- `writeCeilingBytes`: interval write ceiling used by the controller.

The controller uses a per-interval write pressure estimate:

```text
writePressure = max(intervalAdmittedBytes, intervalLogBytesWritten)
```

If `writePressure` exceeds `writeCeilingBytes`, AdaKanga tightens admission. If write pressure is safe and the interval miss rate is stable, AdaKanga increases capacity by increasing KLog fraction or KLog partitions.

## Generated workloads

`scripts/generate_phase10_workload.py` generates configs under `configs/phase10/`.

### Workload-shift trace

The shift trace alternates:

1. A high-hit phase using repeated popular objects.
2. A cold-object phase using many new objects.
3. Another high-hit phase.

Fixed configs are generated with different admission ratios, log fractions, and KLog partition counts.

### Static reference trace

The static reference workload uses many repeated object accesses over a stable population. It is designed to produce candidate evictions and a meaningful fixed vs adaptive comparison.

## Validation

Run:

```bash
python3 scripts/generate_phase10_workload.py
bash scripts/build.sh
python3 scripts/validate_phase10.py
```

The validator writes:

```text
results/phase10/summary.json
```

It checks:

- Adaptive static miss rate is within 2% of the best fixed static config.
- Adaptive shift miss rate is strictly lower than the best fixed shift config.
- Adaptive runs keep the observed interval write pressure within the configured ceiling.

## Current result

At the current Phase 10 settings:

- Static adaptive miss rate is within 2% of the best fixed static config.
- Adaptive shift miss rate is lower than the best fixed shift config.
- AdaKanga observes and reports `maxIntervalWriteBytes` and `writeCeilingBytes` in the stats output.

## Limitations

The controller is intentionally small and rule-based. It does not learn a full utility function or model future workload phases. It uses short interval miss-rate pressure, write ceiling pressure, and bounded capacity/admission changes to avoid large oscillations.
