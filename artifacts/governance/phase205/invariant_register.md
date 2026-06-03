# Invariant Register — Phase 205

| Invariant ID | Sentinel Class | Enforcement Point |
|---|---|---|
| CMVG-CHAIN-0 | CMVGChainError | VelocityLedger.verify_chain(), append() |
| CMVG-IMMUT-0 | CMVGImmutError | VelocityDecision.seal(), VelocityLedger.append() |
| CMVG-HUMAN0-0 | CMVGAuthError | emergency_stop(), clear_emergency_stop(), set_policy_rate(), clear_policy_rate() |
| CMVG-CGDR-0 | — | ConstitutionalMutationVelocityGovernor.decide() — first gate |
| CMVG-DETERM-0 | — | _decision_id(), _compute_rate() — no entropy/time in value fields |
| CMVG-AUDIT-0 | CMVGLedgerError | decide() — commit before return |
| CMVG-FLOOR-0 | CMVGFloorError | _compute_rate() clamp + guard |
| CMVG-CEIL-0 | CMVGCeilError | _compute_rate() clamp + guard, set_policy_rate() |
| CMVG-FAILCLOSED-0 | CMVGError | decide() except block → HALT fallback |
| CMVG-SEAL-0 | CMVGImmutError | VelocityDecision.seal() + _commit() |

**Cumulative Hard-class invariants after Phase 205: 677**
