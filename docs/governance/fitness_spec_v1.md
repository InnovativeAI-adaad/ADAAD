# Fitness Contract Specification v1

This document is the normative contract for mutation fitness scoring used by `runtime/evolution/economic_fitness.py`.

## Governance inputs

- Config file: `runtime/evolution/config/fitness_weights.json`
- Schema contract: `schemas/fitness_weights.schema.json`
- Current config version: `1`
- Current canonical config hash (SHA-256):
  - `sha256:4883ceb55081e6c743217ea1051fa5cf594ac79ead9bc7e338c73003f57efd7b`

Implementations MUST emit both `config_version` and `config_hash` in decision explainability payloads.

## Metric contract

All metrics are normalized to `[0.0, 1.0]`.

| Metric | Weight | Normalization range | Pass/Fail interpretation |
|---|---:|---|---|
| `correctness_score` | 0.30 | clamped to `[0,1]` | Higher means stronger evidence of syntax/tests/sandbox correctness. |
| `efficiency_score` | 0.20 | clamped to `[0,1]` from memory/CPU/runtime derived signals | Higher means lower runtime resource cost. |
| `policy_compliance_score` | 0.20 | clamped to `[0,1]` based on constitution/policy validity and violations | `0.0` when explicit violation is present. |
| `goal_alignment_score` | 0.15 | clamped to `[0,1]` from goal graph alignment/completion | Higher means mutation aligns better to declared objectives. |
| `simulated_market_score` | 0.15 | clamped to `[0,1]` from task-value proxies | Higher means stronger expected utility/value. |

## Decision semantics

- Composite score = weighted sum of normalized metrics.
- Acceptance threshold = `0.70`.
- **Acceptance gate**: proposal is accepted only when base fitness score >= threshold.
- **Ranking signal**: ranking MAY apply additional objective weighting after base scoring, but MUST NOT override acceptance gate semantics.

## Explainability contract

Per-decision payloads MUST include:

- `score`
- `weights`
- `breakdown`
- `weighted_contributions`
- `fitness_threshold`
- `threshold_rationale` (explicit accept/reject rationale)
- `config_version`
- `config_hash`

## Drift prevention requirements

Fitness config validation MUST fail closed when:

- weight keys are missing,
- undocumented weight keys are present,
- total weight is zero/non-positive,
- config payload is malformed.

These checks are enforced by contract tests in `tests/evolution/test_fitness_weights_contract.py`.
