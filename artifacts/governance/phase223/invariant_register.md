# Invariant Register — Phase 223 · INNOV-128 · CPVE

**Cumulative Hard-class total after Phase 223:** 851
**Phase 223 additions:** 10

| ID              | Class | Module                                            | Description                                      |
|-----------------|-------|---------------------------------------------------|--------------------------------------------------|
| CPVE-CHAIN-0    | Hard  | constitutional_provenance_verification_engine.py  | Every record HMAC-SHA-256 chained to predecessor |
| CPVE-APPEND-0   | Hard  | constitutional_provenance_verification_engine.py  | Ledger append-only; atomic via os.replace        |
| CPVE-ORIGIN-0   | Hard  | constitutional_provenance_verification_engine.py  | Every artifact must carry traceable origin_id    |
| CPVE-VERIFY-0   | Hard  | constitutional_provenance_verification_engine.py  | Verification via hmac.compare_digest (timing-safe)|
| CPVE-CERT-0     | Hard  | constitutional_provenance_verification_engine.py  | Certificates require HUMAN-0 authorization       |
| CPVE-DETERM-0   | Hard  | constitutional_provenance_verification_engine.py  | Identical inputs → identical provenance_digest   |
| CPVE-GATE-0     | Hard  | constitutional_provenance_verification_engine.py  | UNVERIFIED/QUARANTINE blocks promotion fail-closed|
| CPVE-AUDIT-0    | Hard  | constitutional_provenance_verification_engine.py  | Every op emits chained audit ledger entry        |
| CPVE-IMMUT-0    | Hard  | constitutional_provenance_verification_engine.py  | Ledger path + HMAC secret immutable post-init    |
| CPVE-SCOPE-0    | Hard  | constitutional_provenance_verification_engine.py  | Exactly 5 Arc II artifact classes in scope       |

## Artifact Classes in Constitutional Scope (CPVE-SCOPE-0)

1. INVARIANT
2. MUTATION
3. ATTESTATION
4. AMENDMENT
5. CERTIFICATE
