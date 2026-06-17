# Phase 215 · INNOV-120 · CGVF — Tier Summary

**Date:** 2026-06-07  
**Version:** 10.26.0  
**Governor:** DUSTIN L REID  
**Author:** DEVADAAD · InnovativeAI LLC

## Hard-Class Invariants Added This Phase (+12 → Cumulative: 767)

| ID | Module | Description | Exception Class |
|----|--------|-------------|-----------------|
| CGVF-AUDIT-0 | constitutional_governance_validation_fusion.py | Every fusion run ledger-recorded before return | CGVFError |
| CGVF-CHAIN-0 | constitutional_governance_validation_fusion.py | HMAC-SHA-256 chained ledger; no gaps tolerated | CGVFChainError |
| CGVF-DETERM-0 | constitutional_governance_validation_fusion.py | fusion_id is SHA-256(peer_signal_hash+ts_ns) | CGVFError |
| CGVF-FAILCLOSED-0 | constitutional_governance_validation_fusion.py | All internal errors raise; never swallowed | CGVFError |
| CGVF-ATOMIC-0 | constitutional_governance_validation_fusion.py | Ledger writes use os.replace() via .tmp | CGVFError |
| CGVF-HUMAN0-0 | constitutional_governance_validation_fusion.py | consensus_score < 0.70 → human0_required=True | CGVFError |
| CGVF-SCORE-0 | constitutional_governance_validation_fusion.py | consensus_score ∈ [0.0, 1.0]; out-of-range raises | CGVFScoreError |
| CGVF-PEER-0 | constitutional_governance_validation_fusion.py | All 4 CG* peers queried; missing peer degrades score | CGVFError |
| CGVF-SEAL-0 | constitutional_governance_validation_fusion.py | Every ledger record carries a sealed HMAC digest | CGVFError |
| CGVF-IMMUT-0 | constitutional_governance_validation_fusion.py | Appended records immutable; mutation raises | CGVFImmutError |
| CGVF-CERT-0 | constitutional_governance_validation_fusion.py | HUMAN-0 certification is one-way; re-certify raises | CGVFCertError |
| CGVF-CONSENSUS-0 | constitutional_governance_validation_fusion.py | overall_status derived solely from score thresholds | CGVFConsensusError |

## Hardening Criteria (5/5 Satisfied)

- [x] Named invariant constant block (`CGVF_AUDIT_0 = "CGVF-AUDIT-0"` etc.)
- [x] Typed RuntimeError subclass (`CGVFError(RuntimeError)`)
- [x] Chain-linked ledger dataclass with `prev_digest` (`FusionAttestation`)
- [x] Append-only JSONL persistence (ledger written via JSONL append + `os.replace()`)
- [x] `hmac.compare_digest` throughout (verify_chain uses `hmac.compare_digest`)

## REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /cgvf/fuse | Run governance fusion cycle |
| POST | /cgvf/certify/{fusion_id} | HUMAN-0 certification gate |
| GET | /cgvf/history | Paginated FusionAttestation log |
| GET | /cgvf/verify-chain | HMAC chain integrity check |
| GET | /cgvf/consensus-score | Live consensus score |
| GET | /cgvf/status | Module health |
