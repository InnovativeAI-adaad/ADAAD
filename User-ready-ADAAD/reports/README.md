# reports

Reports is the observability layer. It is append-only by convention.
It is not a source of truth for governance. That belongs to security/ledger.

## Required files

reports/metrics.jsonl
  - append-only event stream for cycles, stages, tool runs, and health signals

reports/health.log
  - boot and runtime health lines

## Metrics discipline

1) JSONL only. One event per line.
2) Use compact JSON objects.
3) Prefer stable keys and machine-readable values.
4) Do not store secrets, keys, or private material.
5) Prefer references and hashes over large blobs.

## Event shapes

This repo supports two common event families:

1) Mutation stage metrics (system-level)
  - cycle_id
  - parent_agent_id
  - child_candidate_id
  - stage
  - result
  - duration_ms
  - error_code

2) Tool stage metrics (tool-level)
  - event_type
  - status
  - detail
  - timestamp

Both are allowed. Keep them consistent within a pipeline.

## Governance boundary

reports/ is not authoritative.
Policy and certification decisions must be traceable to security/ledger events.
