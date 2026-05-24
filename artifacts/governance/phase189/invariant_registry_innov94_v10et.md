# Invariant Registry — INNOV-94 · V10ET
**Phase 189 · v9.122.0 · Cumulative Hard-class count: 522**

| ID | Name | Class | Description | Violation Exception |
|----|------|-------|-------------|---------------------|
| V10ET-SCOPE-0 | Read-Only Scope | Hard | V10ET reads only GTC release ledger, VERSION, and agent state; never mutates upstream state | V10ETScopeError |
| V10ET-CHAIN-0 | HMAC Chain Integrity | Hard | Epoch ledger entries form valid HMAC-SHA-256 chain; broken chain halts with non-zero exit | V10ETChainError |
| V10ET-HUMAN0-0 | HUMAN-0 Advisory Gate | Hard | HUMAN-0 Track B runbook must be emitted and recorded before epoch seal is finalised; non-skippable | V10ETHuman0Error |
| V10ET-EPOCH-0 | One-Way Epoch Boundary | Hard | v9→v10 transition is irreversible; rollback attempt raises V10ETEpochError and halts | V10ETEpochError |
| V10ET-VERIFY-0 | Merkle Root Re-Validation | Hard | Epoch seal independently re-validates GTC Merkle root; mismatch raises V10ETVerifyError and halts | V10ETVerifyError |

## Cumulative Invariant Count: 522
Previous phase count: 517 (Phase 188 · INNOV-93 · GTC)
Added this phase: 5
Total: 522
