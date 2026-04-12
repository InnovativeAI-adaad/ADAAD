# Compliance Exports API

The compliance exports API provides governance-aligned snapshots and export jobs for major GRC evidence workflows.

## Endpoints

### 1) Read exports directly

`GET /api/compliance/exports/{dataset}?fmt={json|csv}&limit={1..1000}&offset={0..N}&cursor={o:<offset>}`

Supported datasets:

- `control-evidence-snapshots`
- `immutable-replay-attestations`
- `policy-change-history`
- `incident-remediation-logs`

Authentication: bearer token with `audit:read` scope.

### 2) Create export jobs

`POST /api/compliance/exports/{dataset}/jobs?fmt={json|csv}&limit={1..1000}&offset={0..N}&cursor={o:<offset>}`

The job endpoint writes immutable export artifacts under:

- `reports/compliance_exports/*.json`
- `reports/compliance_exports/*.csv`

Each response includes `job_id`, `record_count`, `created_at`, artifact path, pagination metadata, snapshot/version metadata, and dataset indexes (where available).

## Format contracts

## JSON

JSON exports include:

- `schema_version`
- `dataset`
- `record_count`
- `pagination` (`limit`, `offset`, `cursor`, `next_cursor`, `has_more`, `returned_records`, `total_records`)
- `snapshot` (`snapshot_id`, `source_version`)
- `indexes` (dataset-specific summaries for hot collections)
- `records[]`

The direct API response also includes `authn` context and wraps records under `data`.

## CSV

CSV exports are tabular snapshots intended for GRC tooling ingestion.

- Header row is deterministic and alphabetically sorted.
- Nested objects are serialized as canonical JSON strings.
- Empty datasets return an empty CSV body.
- CSV and JSON responses are streamed to reduce peak memory usage on large exports.
- `limit` is capped at `1000` for safe bounds; values above that are rejected by request validation.

## Dataset mappings

### `control-evidence-snapshots`

Control evidence snapshot records currently include:

- claims evidence matrix digest (`docs/comms/claims_evidence_matrix.md`)
- runtime governance profile digest (`governance_runtime_profile.lock.json`)
- immutable replay attestation digest references

### `immutable-replay-attestations`

Replay attestation exports are sourced from `security/replay_manifests/*.replay_attestation.v1.json` and include epoch-level digest metadata.

### `policy-change-history`

Policy history combines:

- current baseline policy artifact (`governance/governance_policy_v1.json`)
- governance/policy-related journal entries from the ledger
- includes precomputed `indexes.tx_type_counts` in the response metadata

### `incident-remediation-logs`

Incident/remediation exports aggregate journal entries whose transaction or payload content references incident, remediation, or recovery events.

- includes precomputed `indexes.status_counts` and `indexes.severity_counts` in the response metadata

## Connector guides (major GRC workflows)

### Splunk

1. Use `fmt=json` and schedule `POST /jobs` daily.
2. Monitor `record_count` for drift.
3. Ingest artifacts from `reports/compliance_exports/` with source type per dataset.

### ServiceNow GRC

1. Use `fmt=csv` for control test evidence imports.
2. Map `control_id`, `snapshot_type`, `sha256`, and `timestamp` to control evidence fields.
3. Attach artifact path as import metadata for audit traceability.

### Microsoft Sentinel / Log Analytics

1. Use `fmt=json` for replay and incident datasets.
2. Normalize `epoch_id`, `tx_type`, and `severity` as queryable columns.
3. Build alerts on new high-severity incident records and replay digest deltas.

### AuditBoard / Archer workflows

1. Pull `control-evidence-snapshots` weekly (CSV) for control walkthroughs.
2. Pull `policy-change-history` monthly (JSON) for policy governance committee review.
3. Pull `incident-remediation-logs` post-incident for CAPA evidence packets.
