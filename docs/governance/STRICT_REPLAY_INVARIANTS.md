# Strict Replay Invariants

## Scope

This document defines the invariants that must hold for strict replay validation and how they differ from forensic reconstruction workflows.

## Core invariants

1. **Deterministic provider is mandatory in strict replay mode.**
   - Strict replay must fail closed when a non-deterministic provider is configured.
2. **Verified digest paths require append-only chain integrity.**
   - `compute_incremental_epoch_digest(...)` and `ReplayEngine.compute_incremental_digest(...)` must validate ledger integrity before producing a digest.
3. **Unverified digest paths are forensic-only.**
   - `compute_incremental_epoch_digest_unverified(...)` and `ReplayEngine.compute_incremental_digest_unverified(...)` are for forensic reconstruction and drift analysis only.
   - They must never be used as authoritative inputs for production promotion validation.
4. **Nonce ordering anomalies are auditable in strict replay lanes.**
   - Malformed nonce values emit deterministic warning events (`strict_replay_malformed_nonce`).
5. **Replay equivalence guarantee.**
   - Given identical ledger inputs and deterministic providers, strict replay must produce identical epoch digest outcomes.

6. **Hermetic runtime profile must validate before governance-critical boot.**
   - `governance_runtime_profile.lock.json` is the canonical runtime lock artifact.
   - dependency fingerprint must match the pinned lock target (`requirements.server.txt`).
   - mutable filesystem and network surfaces must be disabled or explicitly allowlisted.
7. **Fail-closed boot posture.**
   - Any runtime profile mismatch (fingerprint/provider/surface policy) must halt boot prior to mutation execution.

## Operational guidance

- Use verified digest APIs for policy gates and production governance decisions.
- Use unverified digest APIs only for incident response, tamper triage, and post-mortem analytics.
- Treat any strict replay warning as a governance health signal and investigate before re-enabling promotion flows.
