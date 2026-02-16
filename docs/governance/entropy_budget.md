# Entropy Budget Baseline and Tuning

This guide defines the operational process for tuning deterministic-envelope budgets.

## Baseline Collection

Run the profiler against your lineage ledger:

```bash
PYTHONPATH=. python tools/profile_entropy_baseline.py \
  --ledger /var/adaad/lineage_v2.jsonl \
  --lookback 100 \
  --json > reports/entropy_baseline.json
```

Key fields:

- `consumed_max_p95`: high-percentile entropy load per epoch.
- `overflow_total`: count of budget overflows observed.
- `drift.drift_detected`: whether entropy trends are rising materially.

## Recommended Budget Formula

Default recommendation in profiler:

```
recommended_budget = floor(consumed_max_p95 * 1.2 + 10)
```

You can adjust with flags:

- `--headroom` (default `1.2`)
- `--offset` (default `10`)

## Tuning Policy

1. Keep `overflow_total` at `0` during normal operation.
2. If overflows occur with no drift, increase budget conservatively.
3. If drift is detected repeatedly, investigate entropy regressions before raising budget.
4. Re-profile after each constitution/governor change.

## CI/Automation Suggestion

Use drift as an advisory gate in scheduled jobs:

```bash
PYTHONPATH=. python tools/profile_entropy_baseline.py --lookback 20 --json
```

Alert when:

- `drift.drift_detected == true`
- or `overflow_total > 0`


## CI Gate Modes

The profiler supports fail-fast exit codes for automation:

```bash
# Exit 2 if drift is detected
PYTHONPATH=. python tools/profile_entropy_baseline.py --lookback 20 --fail-on-drift

# Exit 3 if any overflows were observed
PYTHONPATH=. python tools/profile_entropy_baseline.py --lookback 20 --fail-on-overflow
```

You can combine both flags in the same run.
