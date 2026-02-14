# Autonomy Feature Schema (Beast Mode)

`BeastModeLoop` can evaluate staged mutations with an autonomy composite score when all required features are present in `mutation.json`.

## Required feature fields

At least one synonym from each group must be present and numeric (`int` or `float`):

- **expected gain**: `expected_gain` | `fitness_gain` | `estimated_gain`
- **risk score**: `risk_score` | `risk` | `estimated_risk`
- **complexity**: `complexity` | `complexity_score` | `estimated_complexity`
- **coverage delta**: `coverage_delta` | `test_coverage_delta` | `coverage_change`

## Optional identity field

- `mutation_id` (string, preferred)

If `mutation_id` is absent, Beast Mode computes a deterministic fallback ID from canonicalized payload JSON (`payload-<sha256-prefix>`).

## Scoring behavior

- When all four feature groups are present, Beast Mode uses autonomy scoring (`rank_mutation_candidates`) with `ADAAD_AUTONOMY_THRESHOLD`.
- When one or more feature groups are missing, Beast Mode falls back to legacy fitness threshold gating (`ADAAD_FITNESS_THRESHOLD`) and emits `beast_autonomy_fallback` telemetry.

## Example

```json
{
  "parent": "agentA",
  "mutation_id": "mutation-2026-02-14-001",
  "expected_gain": 0.72,
  "risk_score": 0.15,
  "complexity": 0.20,
  "coverage_delta": 0.08
}
```
