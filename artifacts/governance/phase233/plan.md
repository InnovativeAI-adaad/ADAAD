# Phase Plan — Phase 233 · INNOV-138 · EVE

**Innovation:** INNOV-138 · EVE — External Verifiability Engine
**Arc:** IV — External Verifiability & Federation (OPENED)
**SPIE Signal:** `constitutional_gap` · `external_verifiability` · gap_score 1.00
**Ratified:** DUSTIN L. REID / HUMAN-0 · 2026-06-21
**Proposal ID:** spie:4f75db25a631a8fe

## Motivation

Arc III (ACI) achieved full internal autonomous governance: CASL → CADE → CAPE → CAVE → CAOE → CALI → CACP → CAMS → CACG. The loop is FULLY CLOSED internally. The SPIE evaluation (epoch arc4-open-20260621) identified a constitutional gap of 1.00 in `external_verifiability`: zero invariants govern the ability of a third party to independently verify ADAAD's governance claims.

EVE closes this gap by introducing externally-auditable AttestationBundles — self-contained JSON objects that encode CHI scores, ACI cycle proofs, invariant register snapshots, and SPIE ratification events in a form any external auditor can cryptographically verify.

## Design Decisions

1. **Four proof types** map directly to the four most strategically significant internal data sources: CHI (constitutional health), ACI_CYCLE (governance cycle outcomes), INVARIANT_REGISTER (invariant compliance), SPIE (innovation ratification provenance).
2. **EVE-EXTERN-0** ensures no private HMAC secret escapes the export boundary — only the public key name is included, with verification instructions. This makes bundles safe to publish publicly.
3. **EVE-DETERM-0** enables replay verification: given the same proof inputs, any verifier recomputes the same digest, without needing access to ADAAD internals.
4. **EVE-HUMAN0-0** preserves the Track B governance model: attestation publication remains gated on HUMAN-0 identity, maintaining non-delegatable human authority over external claims.
5. **Arc IV scope**: EVE is intentionally scoped to the single-instance verifiability problem. Multi-instance federation (Candidate 2) and cross-arc provenance synthesis (Candidate 5) are reserved for subsequent Arc IV phases.

## Deliverables

| Artifact | Path |
|---|---|
| Core engine | `dorkllm/external_verifiability_engine.py` |
| FastAPI router | `app/api/eve.py` |
| Acceptance tests | `tests/test_phase233_eve.py` |
| ILA attestation | `artifacts/governance/phase233/ILA_attestation.md` |
| Tier summary | `artifacts/governance/phase233/tier_summary.md` |
| Invariant register | `artifacts/governance/phase233/invariant_register.md` |
| Plan | `artifacts/governance/phase233/plan.md` |
