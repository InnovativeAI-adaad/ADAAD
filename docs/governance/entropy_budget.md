# Entropy Budget Baseline and Tuning

This guide defines the operational process for tuning deterministic-envelope budgets.

## Baseline Collection

Run the profiler against your lineage ledger for percentile and recommendation collection:

```bash
PYTHONPATH=. python tools/profile_entropy_baseline.py \
  --ledger /var/adaad/lineage_v2.jsonl \
  --lookback 100 \
  --json > reports/entropy_baseline_$(date +%Y-%m-%d).json
```

Key fields:

- `consumed_max_p95`: high-percentile entropy load per epoch.
- `overflow_total`: count of budget overflows observed.
- `drift.drift_detected`: whether entropy trends are rising materially.

Then run the explicit drift gate command:

```bash
PYTHONPATH=. python tools/profile_entropy_baseline.py --lookback 20 --json | jq -e '.drift.drift_detected == false and .overflow_total == 0'
```

This command fails fast when either drift is detected or overflow is non-zero.

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

## Success Criteria

- Baseline percentile and recommendation artifacts are collected using:

  ```bash
  PYTHONPATH=. python tools/profile_entropy_baseline.py \
    --ledger /var/adaad/lineage_v2.jsonl \
    --lookback 100 \
    --json > reports/entropy_baseline_$(date +%Y-%m-%d).json
  ```

- Drift gate passes (no drift and no overflow) using:

  ```bash
  PYTHONPATH=. python tools/profile_entropy_baseline.py --lookback 20 --json | jq -e '.drift.drift_detected == false and .overflow_total == 0'
  ```

- Recommended budget is extracted from the most recent baseline artifact.

- Tuned budget is applied via environment variable or governor default after approval.

## CI/Automation Suggestion

Use the same drift gate command in scheduled jobs to keep manual and automated procedures aligned:

```bash
PYTHONPATH=. python tools/profile_entropy_baseline.py --lookback 20 --json | jq -e '.drift.drift_detected == false and .overflow_total == 0'
```

For runbook budget extraction, always target the single most recent baseline artifact:

```bash
latest=$(ls -1t reports/entropy_baseline_*.json 2>/dev/null | head -n1)
jq '.recommended_budget' "$latest"
```

In CI/cron, fail fast if no matching file exists:

```bash
latest=$(ls -1t reports/entropy_baseline_*.json 2>/dev/null | head -n1)
test -n "$latest"
jq '.recommended_budget' "$latest"
```

Budget updates must use the most recent baseline artifact only.

Suggested CI smoke test snippet for entropy/governor + determinism coverage:

```bash
PYTHONPATH=. pytest -q \
  tests/test_evolution_governor.py \
  tests/test_entropy_budget.py \
  tests/determinism/
```

## Phase 2 Tuning Decision Log (Append-Only)

To avoid process drift, keep all Phase 2 historical decisions in this single section rather than creating standalone documents. Add one dated entry per approved tuning change and do not edit prior entries other than minor typo fixes.

### 2026-02-16 — Phase 2 tuning decision

- **Baseline artifact reference:** `reports/entropy_baseline_<YYYY-MM-DD>.json` (most recent artifact at decision time).
- **Observed percentiles:**
  - `p50`: `<value>`
  - `p95`: `<value>`
  - `p99`: `<value>`
- **Formula and computed recommendation:**
  - Formula: `recommended_budget = floor(p95 * 1.2 + 10)`
  - Computation: `floor(<p95> * 1.2 + 10) = <recommended_budget>`
- **Selected budget and approval metadata:**
  - Selected budget: `<selected_budget>`
  - Approver: `<name or role>`
  - Approval channel: `<ticket/PR/change-request>`
  - Approval timestamp (UTC): `<YYYY-MM-DDThh:mm:ssZ>`
- **Applied commit link:** `<commit hash or URL>`

When completing a real decision entry, resolve placeholders with exact values from the baseline JSON and the approval record.

## Post-Deployment Actions

- Immediate verification:

  ```bash
  PYTHONPATH=. pytest -q tests/determinism/test_filesystem_wrapper_migration.py
  ```

- Suggested smoke verification:

  ```bash
  PYTHONPATH=. pytest -q \
    tests/test_evolution_governor.py \
    tests/test_entropy_budget.py \
    tests/determinism/
  ```

- If triaging only entropy-related governor behavior:

  ```bash
  PYTHONPATH=. pytest -q tests/test_evolution_governor.py -k entropy
  ```

- Week 2 baseline profiling and extraction:

  ```bash
  PYTHONPATH=. python tools/profile_entropy_baseline.py \
    --lookback 100 \
    --json > reports/entropy_baseline_$(date +%Y-%m-%d).json

  latest=$(ls -1t reports/entropy_baseline_*.json 2>/dev/null | head -n1)
  test -n "$latest"
  jq '.consumed_max_p95, .recommended_budget' "$latest"
  ```

## CI Gate Modes

The profiler supports fail-fast exit codes for automation:

```bash
# Exit 2 if drift is detected
PYTHONPATH=. python tools/profile_entropy_baseline.py --lookback 20 --fail-on-drift

# Exit 3 if any overflows were observed
PYTHONPATH=. python tools/profile_entropy_baseline.py --lookback 20 --fail-on-overflow
```

You can combine both flags in the same run.
