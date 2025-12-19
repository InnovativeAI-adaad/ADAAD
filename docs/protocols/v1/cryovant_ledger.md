# Protocol v1.0: Cryovant Ledger Contract

## Purpose
Define the append-only JSONL schema Cryovant uses to record certification, lineage, and gatekeeping outcomes. Ledger entries are the single source of truth for promotions and must be writable at boot or boot fails.

## Location
`security/ledger/events.jsonl`

## Schema (one JSON object per line)
```json
{
  "ts": "ISO-8601 timestamp in UTC",
  "action": "certify|ledger_probe|promotion|doctor_probe|other",
  "actor": "cryovant|gatekeeper|doctor|system|<caller>",
  "outcome": "ok|error|accepted|rejected",
  "agent_id": "string identifier of the agent (if applicable)",
  "lineage_hash": "deterministic hash of agent lineage or metadata",
  "signature_id": "signature or record id, may be stubbed but must be present",
  "detail": { "optional": "additional context" }
}
```

## Rules
- File must be append-only; no rewrites or truncation.
- Writes must pass through Cryovant helpers.
- Boot fails if the ledger directory is not writable.
- No other component should emit to this file directly.
