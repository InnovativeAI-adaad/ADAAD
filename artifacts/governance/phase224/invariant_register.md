# Phase 224 · CASL — Invariant Register

**Cumulative Hard-class invariants after Phase 224: 861**

## New Hard-class Invariants (Phase 224)

```
CASL-CHAIN-0   : All synthesis ledger entries HMAC-SHA-256 chained; chain break raises ChainBreakError
CASL-APPEND-0  : Synthesis ledger append-only; ImmutabilityViolation on attempted mutation/deletion
CASL-CHI-0     : CHI computation requires exactly 9 Arc II domains; CHIComputationError otherwise
CASL-GATE-0    : Synthesis gate fail-closed; SynthesisGateError blocks on any unverified signal
CASL-DETERM-0  : CHI computation is deterministic; same inputs produce same CHI with same anchor HMAC
CASL-AUDIT-0   : Every operation (ingest, synthesize, verify, gate-check) recorded in append-only audit log
CASL-VERIFY-0  : All inbound domain signals verified via hmac.compare_digest; VerificationFailure on mismatch
CASL-SCOPE-0   : Exactly 9 Arc II domain classes in ARC_II_DOMAINS; ScopeViolation on unregistered domain
CASL-IMMUT-0   : SynthesisRecord sealed on first append; ImmutabilityViolation on re-seal or re-append
CASL-ORIGIN-0  : Every synthesis call requires non-empty provenance_ref; OriginViolation otherwise
```

## Module: dorkllm/constitutional_arc_synthesis_layer.py
## Router:  app/api/casl.py
## Tests:   tests/test_phase224_casl.py (T224-CASL-01 → T224-CASL-30, 30/30 PASS)
