# Phase 126 — Invariant Registry
# Red-Team Challenge · v9.59.0 · ILA-126-2026-04-06-001

| ID               | Class | Definition                                                                                              | Gate Exception              |
|------------------|-------|---------------------------------------------------------------------------------------------------------|-----------------------------|
| REDTEAM-IMMUT-0  | Hard  | Attack ledger is append-only. Post-write mutation of any record raises `LedgerMutationError`. Tamper detection via `hmac.compare_digest`. | `LedgerMutationError`       |
| REDTEAM-AUDIT-0  | Hard  | Every attack attempt must be persisted to the chain-linked ledger before the next attempt begins. Ledger write failure raises `ConstitutionalBreachError`. | `ConstitutionalBreachError` |
| REDTEAM-SCOPE-0  | Hard  | The attacker may only target invariants explicitly listed in the canonical `AttackManifest`. Attacks against unlisted targets raise `OutOfScopeAttackError` and are logged but not executed. | `OutOfScopeAttackError`     |
| REDTEAM-HALT-0   | Hard  | If any Hard-class gate fails to fire against an attack payload designed to trigger it, the attacker raises `ConstitutionalBreachError` immediately and halts. Silent pass-through is categorically prohibited. | `ConstitutionalBreachError` |
| REDTEAM-DETERM-0 | Hard  | The `run_digest` of every `CampaignReport` must be a pure function of (campaign_id, attack_ids, outcomes). Clock reads and random state must never appear in digest computation. | `ConstitutionalBreachError` |
| REDTEAM-CHAIN-0  | Hard  | Each `AttackRecord` must carry `prev_digest` linking to the SHA-256 digest of the immediately preceding record. The first record carries `prev_digest="genesis"`. | `ConstitutionalBreachError` |

## Cumulative Hard-class count
- Prior (post-Phase 125): **167**
- Added this phase:       **+6**
- Post-Phase 126:         **173**
