# Federation Conflict Runbook

This runbook covers deterministic response for replay divergence across federated peers.

## Scenario: Peer digest conflict

Symptoms:
- Local replay digest differs from one or more peers.
- Replay verification event includes conflict classes such as `federated_split_brain` or `cross_node_attestation_mismatch`.

## Response steps

1. Confirm local divergence classification and precedence decision.
   - Inspect `/replay/divergence`
   - Inspect `/replay/diff?epoch_id=<epoch-id>`
2. Export local forensic bundle and capture `bundle_id` and `export_metadata.digest`.
3. Collect corresponding peer evidence bundle and replay proof bundle.
4. Compare:
   - replay digest (`replay_proofs`)
   - checkpoint chain digest
   - policy artifact metadata fingerprint
5. If peer signatures verify but digests differ, treat as governance incident:
   - hold promotion
   - keep precedence policy explicit (`local`, `federated`, or `both`)
   - open incident for root-cause triage (partition, config skew, genuine divergence)

## Scenario: unreachable peer

1. Mark peer status degraded in federation operations log.
2. Apply configured precedence mode deterministically.
3. Continue read-only replay verification and capture mismatch context in lineage events.
4. Reconcile once connectivity is restored; do not rewrite prior evidence.

## Escalation trigger

Escalate immediately when:
- divergence persists across multiple epochs,
- quorum cannot be reached,
- or policy precedence flips repeatedly between runs.


## Implementation reference

- Founders-law compatibility helpers used by federation tests are implemented at `runtime/governance/founders_law_v2.py`.
- Verify local availability with: `PYTHONPATH=. pytest -q tests/test_founders_law_v2.py tests/governance/test_federation_coordination.py`.
