# adaad-core

**Constitutional Governance Kernel for ADAAD**

`adaad-core` is the independently installable governance kernel extracted from [ADAAD](https://github.com/InnovativeAI-adaad/adaad) — the first constitutionally governed autonomous code evolution runtime.

## Install

```bash
pip install adaad-core
```

## Usage

```python
from adaad_core import (
    GovernanceGate,
    ConstitutionalRollbackEngine,
    InvariantDiscoveryEngine,
    MirrorTestEngine,
    EpochMemoryStore,
    verify_ledger,
)

# Evaluate a mutation candidate against the constitution
gate = GovernanceGate.from_config("config/constitution.yaml")
result = gate.evaluate(candidate)  # APPROVED · RETURNED · BLOCKED

# Verify ledger chain integrity
chain_ok = verify_ledger("data/evolution_ledger.jsonl")
print("Ledger integrity:", chain_ok)  # True = unbroken hash chain
```

## What's included

Six semver-governed exports (invariant: `CORE-EXPORT-0`):

| Export | Role |
|--------|------|
| `GovernanceGate` | Deterministic gate evaluation — APPROVED / RETURNED / BLOCKED |
| `ConstitutionalRollbackEngine` | Amendment versioning and rollback to any prior state |
| `InvariantDiscoveryEngine` | Autonomous constitutional rule discovery from failure ledger |
| `MirrorTestEngine` | Constitutional self-recognition test — pipeline seal |
| `EpochMemoryStore` | Ledger-backed epoch memory with deterministic replay |
| `verify_ledger` | SHA-256 hash-chain verification of any JSONL ledger |

Breaking changes require `CORE-SEMVER-0` ratification and HUMAN-0 approval.

## Version

`9.75.0` — Phase 142 · 231 Hard-class invariants · 48 innovations shipped

## License

Apache-2.0 · [InnovativeAI LLC](https://adaad.pro)
