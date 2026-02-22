# Replay Proof of Legitimacy Exchange (Sovereign Instances)

## Purpose
This document defines the deterministic, offline "proof of legitimacy" exchange used to verify replay attestation bundles across sovereign ADAAD instances.

## Exchange Artifacts
1. **Replay attestation bundle** (`replay_attestation.v1.json`) exported from source instance.
2. **Verifier keyring** mapping accepted `key_id` values to deterministic verifier key material.
3. **Verifier trust policy** containing:
   - accepted issuer identities,
   - allowed key epoch validity windows,
   - expected trust policy version,
   - revocation ledger snapshot for offline checks.

All artifacts are transferred as immutable files. No runtime state lookup or network dependency is required for verification.

## Required Trust Metadata
When legitimacy checks are enforced, the bundle must include `trust_root_metadata` with:
- `issuer_chain`: ordered issuer chain used for provenance acceptance.
- `key_epoch`: key epoch identifier with validity bounds.
- `revocation_reference`: deterministic pointer to the revocation snapshot used during signing.
- `trust_policy_version`: policy semantic version used by the producer.

## Verification Procedure
1. Validate schema integrity for the bundle.
2. Recompute proof digest over the unsigned payload (including `trust_root_metadata` when present).
3. Verify signatures against explicit keyring entries.
4. Enforce legitimacy policy:
   - at least one issuer in `issuer_chain` must be accepted,
   - `key_epoch` validity must remain within verifier-approved windows,
   - `trust_policy_version` must match verifier expectation,
   - revocation source must not mark the signing key as revoked.

## Determinism Invariants
- Verifier inputs are explicit and file-backed.
- Revocation checks use injected offline resolvers only.
- Bundle verdict is fully reproducible given identical bundle + policy files.
- Verification fails closed when trust metadata is required but absent.

## Operational Guidance
Use `tools/verify_replay_attestation_bundle.py` to validate exported bundles in disconnected environments. Keep exchanged policy/key/revocation files under change control and align trust policy versions prior to federation handoff.
