# Invariant Register — Phase 233 · INNOV-138 · EVE

| ID | Class | Description |
|---|---|---|
| EVE-BUNDLE-0 | Hard | Every AttestationBundle has non-empty bundle_digest (SHA-256 over canonical JSON of all enclosed proofs); fail-closed |
| EVE-CHAIN-0 | Hard | AttestationLedger entries HMAC-SHA-256 chained; chain verified before every append |
| EVE-APPEND-0 | Hard | AttestationLedger append-only; sealed entries raise ImmutabilityViolation on write attempt after sealing |
| EVE-DETERM-0 | Hard | Identical (epoch_id, proof_set) inputs produce identical bundle_digest; no datetime.now(), no uuid4(), no RNG |
| EVE-SCOPE-0 | Hard | Every bundle declares at least one proof_source from {CHI, ACI_CYCLE, INVARIANT_REGISTER, SPIE}; absent raises ScopeViolation |
| EVE-HUMAN0-0 | Hard | Bundle sealing and publication require non-empty HUMAN-0 identity; absent raises PublicationGateError |
| EVE-VERIFY-0 | Hard | verify_bundle() reproduces bundle_digest from enclosed proofs; mismatch raises VerificationFailure |
| EVE-EXTERN-0 | Hard | export_bundle() serialises public HMAC key name + verification instructions; no private secrets embedded |
| EVE-IMMUT-0 | Hard | Sealed AttestationBundles raise ImmutabilityViolation on any field mutation attempt after sealing |
| EVE-AUDIT-0 | Hard | Every EVE operation appended to parallel HMAC-chained audit log before operation returns |

**Total new Hard-class invariants: 10**
**Cumulative Hard-class invariants: 954**
