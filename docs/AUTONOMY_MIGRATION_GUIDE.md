# Autonomy Scoring Migration Guide

This guide explains how to migrate mutation producers to autonomy-first gating in Beast Mode.

## Current behavior

Beast Mode supports dual gating:

1. **Autonomy composite gate** when required autonomy features exist.
2. **Legacy fitness fallback** when required features are missing.

This allows a no-downtime migration.

## Step 1: Emit required autonomy fields

Update mutation producers (architect/mutator pipelines) to include one numeric field from each required group:

- expected gain
- risk score
- complexity
- coverage delta

Prefer canonical field names:

- `expected_gain`
- `risk_score`
- `complexity`
- `coverage_delta`

Also emit stable `mutation_id` values.

## Step 2: Monitor fallback rate

Track `beast_autonomy_fallback` events.

Goal: drive fallback rate toward zero by ensuring all staged payloads contain required autonomy features.

## Step 3: Compare score distributions

Monitor both telemetry fields from Beast Mode:

- `legacy_fitness_score`
- `autonomy_composite_score`

Use these to calibrate `ADAAD_AUTONOMY_THRESHOLD` safely.

## Step 4: Increase policy strictness

After stable rollout and low fallback rates:

- tighten mutation producer validation to require autonomy fields
- keep fallback temporarily for compatibility

## Step 5: Optional autonomy-only mode

When all producers are compliant, you can remove legacy fallback as a deliberate breaking change.

## Operational commands

Use audit CLI scoreboard view for autonomy telemetry snapshots:

```bash
python -m tools.adaad_audit --action autonomy-scoreboard --output json --limit 1000
```
