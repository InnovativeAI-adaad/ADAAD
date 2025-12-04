# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
# Aponi Evolution Dashboard Panels

## Purpose
Aponi provides live observability for mutation health, lineage, and governance signals.

## Endpoints
- `/metrics`: Streams parsed entries from `reports/metrics.jsonl` representing mutation outcomes.
- `/lineage`: Streams Cryovant JSONL mirror entries for ancestry tracing.

## Panels
- Mutation survival rate and trend over recent cycles.
- Lineage graph highlighting certified vs quarantined artifacts.
- Cryovant certification status and mirror health indicators.
- Architect Agent proposal feed for structural violations.
- Warm-pool responsiveness and sandbox latency snapshots.

## Operator Actions
- Monitor for rising quarantine counts and investigate via governance proposals.
- Validate survival deltas align with fitness targets (>80% goal).
- Use lineage data to correlate mutation strategies with outcomes.
