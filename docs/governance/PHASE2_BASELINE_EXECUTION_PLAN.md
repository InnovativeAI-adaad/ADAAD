# ADAAD Phase 2 Execution Plan: Baseline Profiling & Budget Tuning

This document operationalizes Phase 2 with copy/paste commands aligned to the current repository layout and tooling.

## Scope

Phase 2 goals:

1. Profile entropy envelope consumption against lineage history.
2. Validate no drift + no overflow at gate window.
3. Tune governor entropy budget from observed p95.
4. Verify deterministic filesystem migration posture.
5. Establish 7-day entropy health monitoring.

---

## Day 1–2: Baseline Collection & Drift Gate

### 1) Generate baseline artifact (100-epoch window)

```bash
PYTHONPATH=. python tools/profile_entropy_baseline.py \
  --ledger security/ledger/lineage_v2.jsonl \
  --lookback 100 \
  --json > reports/entropy_baseline_$(date +%Y-%m-%d).json
```

Validate artifact exists:

```bash
latest=$(ls -1t reports/entropy_baseline_*.json 2>/dev/null | head -n1)
test -n "$latest"
echo "Baseline artifact: $latest"
```

Extract primary metrics:

```bash
jq '{
  epochs_considered: .epochs_considered,
  decision_events_total: .decision_events_total,
  overflow_total: .overflow_total,
  consumed_max_p95: .consumed_max_p95,
  consumed_avg_p95: .consumed_avg_p95,
  recommended_budget: .recommended_budget,
  drift_detected: .drift.drift_detected
}' "$latest"
```

### 2) Drift gate (fail-fast)

```bash
PYTHONPATH=. python tools/profile_entropy_baseline.py \
  --lookback 20 \
  --json | jq -e '.drift.drift_detected == false and .overflow_total == 0'
```

Optional hard exit code mode:

```bash
PYTHONPATH=. python tools/profile_entropy_baseline.py --lookback 20 --fail-on-drift
PYTHONPATH=. python tools/profile_entropy_baseline.py --lookback 20 --fail-on-overflow
```

---

## Day 3: Budget Tuning

### 3) Extract recommendation from latest baseline

```bash
latest=$(ls -1t reports/entropy_baseline_*.json 2>/dev/null | head -n1)
test -n "$latest"

recommended=$(jq -r '.recommended_budget' "$latest")
p95=$(jq -r '.consumed_max_p95' "$latest")
overflow=$(jq -r '.overflow_total' "$latest")

echo "p95=$p95 overflow=$overflow recommended_budget=$recommended"
```

### 4) Apply budget via environment configuration

```bash
export ADAAD_GOVERNOR_ENTROPY_BUDGET="$recommended"
```

> Notes:
>
> - `EvolutionGovernor` resolution order is: explicit constructor arg > `ADAAD_GOVERNOR_ENTROPY_BUDGET` > default `100`.
> - If `ADAAD_SOVEREIGN_MODE=strict`, missing or invalid env budget fails closed.

### 5) Record decision in governance log

Append actual values into:

- `docs/governance/entropy_budget.md`
- Section: `Phase 2 Tuning Decision Log (Append-Only)`

Required fields: baseline artifact reference, p50/p95/p99, formula calculation, selected budget, approver metadata, commit link.

---

## Day 4: Determinism Migration Verification & Tests

### 6) Canonical migration verifier

```bash
PYTHONPATH=. python tools/verify_filesystem_migration.py
```

This performs:

1. determinism lint on governance/evolution paths,
2. deterministic-wrapper adoption check,
3. non-wrapped filesystem operation scan.

### 7) Determinism and governor tests

```bash
PYTHONPATH=. pytest -q tests/test_evolution_governor.py
PYTHONPATH=. pytest -q tests/test_entropy_budget.py
PYTHONPATH=. pytest -q tests/determinism/
```

Entropy-focused governor triage:

```bash
PYTHONPATH=. pytest -q tests/test_evolution_governor.py -k entropy
```

---

## Day 5: Monitoring Kickoff

### 8) 7-day health snapshot command

```bash
PYTHONPATH=. python tools/monitor_entropy_health.py \
  --ledger security/ledger/lineage_v2.jsonl \
  --days 7 \
  --json
```

Interpretation targets:

- `overflow_events == 0`
- `budget_utilization_pct < 90`
- `status == "ok"` (or policy-defined healthy state)

---

## Completion Checklist

- [ ] Baseline artifact generated with 100-epoch lookback.
- [ ] Drift gate passed (`drift_detected=false`, `overflow_total=0`).
- [ ] Recommended budget extracted from latest artifact.
- [ ] Runtime budget applied via environment/configuration.
- [ ] Phase 2 decision entry recorded in append-only governance log.
- [ ] Filesystem migration verifier passes.
- [ ] Determinism + governor test targets pass.
- [ ] 7-day monitor command operational with expected status.

---

## Expected Metric Envelope (Reference)

- Epochs analyzed: `~100`
- Decision events: `~400–800`
- Overflow total: `0`
- `consumed_max_p95`: `~18–25`
- Recommended budget: `~32–40`
- Drift detected: `false`

These are guidance bands; actual values are authoritative from produced baseline artifacts.
