# Fail-Closed Recovery Runbook

This runbook covers human-in-the-loop recovery for governance fail-closed conditions, including replay divergence and lineage integrity alerts.

## 1) Identify the fail-closed reason

Inspect governance decisions for the active epoch:

```bash
python - <<'PY'
from runtime.evolution.lineage_v2 import LineageLedgerV2
ledger = LineageLedgerV2()
for epoch_id in ledger.list_epoch_ids():
    for entry in ledger.read_epoch(epoch_id):
        if entry.get("type") == "GovernanceDecisionEvent":
            payload = entry.get("payload") or {}
            if payload.get("decision") == "fail_closed":
                print(epoch_id, payload.get("reason"), payload.get("tier"))
PY
```

Typical reasons:
- `replay_divergence`
- `lineage_integrity_error`

## 2) Validate legitimate vs malicious tampering

1. Verify hash-chain integrity directly.
2. Compare expected replay digest with reconstructed digest.
3. Confirm whether divergence was introduced by authorized maintenance.

Quick integrity check:

```bash
python - <<'PY'
from runtime.evolution.lineage_v2 import LineageLedgerV2
ledger = LineageLedgerV2()
ledger.verify_integrity()
print("lineage_integrity:ok")
PY
```

If integrity verification fails, treat as potentially malicious until proven otherwise.

## 3) Recovery procedure

1. Pause mutation execution.
2. Preserve ledger artifacts for audit.
3. Perform operator review of divergent/tampered entries.
4. If false positive, apply approved recovery signature flow via governance controls.
5. Re-run replay preflight in `strict` mode before resuming mutation cycles.

## 4) Post-recovery validation checklist

- Replay preflight returns no divergence for target epoch(s).
- No new `fail_closed` governance decisions are emitted.
- Entropy and sandbox evidence checks continue to pass.
- Snapshot/ledger archival for the incident is complete.

## 5) Observability companion

Use `runtime.evolution.telemetry_audit.get_epoch_entropy_breakdown(...)` for declared vs observed entropy inspection during incident triage.
