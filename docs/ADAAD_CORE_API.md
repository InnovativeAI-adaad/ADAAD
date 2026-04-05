# adaad-core — Stable API Reference

> **Semver-governed from v9.57.0 (Phase 124).**  
> Breaking changes to this surface require a major version bump and HUMAN-0 ratification.

---

## Installation

```bash
pip install adaad-core
```

`adaad-core` installs the constitutional governance kernel only.  
It does **not** pull in Aponi UI, SPIE, federation modules, or HTTP server dependencies.

---

## Public Exports

```python
from adaad_core import GovernanceGate
from adaad_core import ConstitutionalRollbackEngine
from adaad_core import InvariantDiscoveryEngine
from adaad_core import MirrorTestEngine
from adaad_core import EpochMemoryStore
from adaad_core import verify_ledger
```

---

## API Surface

### `GovernanceGate`
Deterministic gate evaluation engine. Evaluates mutation proposals against constitutional rules across multiple axes (AST safety, import policy, complexity, fitness divergence, semantic integrity, exception scope).

```python
gate = GovernanceGate(constitution_path=Path("docs/CONSTITUTION.md"))
decision = gate.evaluate(proposal)
# decision.approved: bool
# decision.reason_codes: list[str]
# decision.failed_rules: list[dict]
```

**Invariants:** `GATE-0`, `GATE-SERIAL-0`, `GATE-DETERM-0`

---

### `ConstitutionalRollbackEngine`
Amendment versioning layer. Every amendment is semantically diffed, chain-linked via `prev_hash`, and reversible to any prior snapshot under HUMAN-0 gate.

```python
engine = ConstitutionalRollbackEngine(state_dir=Path(".adaad/rollback"))
snapshot_id = engine.snapshot(constitution_text)
engine.rollback(snapshot_id)
```

**Invariants:** `CRTV-0`, `CRTV-CHAIN-0`, `CRTV-DETERM-0`, `CRTV-GATE-0`, `CRTV-AUDIT-0`

---

### `InvariantDiscoveryEngine`
Watches failed mutations, extracts recurring failure patterns, proposes new constitutional rules. The system discovers its own laws from its own failure history.

```python
ide = InvariantDiscoveryEngine(state_dir=Path(".adaad/ide"))
rules = ide.analyze_failures(epoch_id="epoch-001", failures=failure_list)
# rules: list[DiscoveredRule]
```

**Invariants:** `IDE-0`, `IDE-DETERM-0`, `IDE-PERSIST-0`, `IDE-AUDIT-0`, `IDE-GATE-0`

---

### `MirrorTestEngine`
Constitutional self-calibration. Every N epochs, presents the system with historical mutation proposals (outcomes redacted) and measures prediction accuracy. Low accuracy triggers `ConstitutionalCalibrationEpoch`.

```python
mirror = MirrorTestEngine(state_dir=Path(".adaad/mirror"))
result = mirror.run(epoch_id="epoch-050", sample=historical_proposals, predictor=my_predictor)
# result.overall_score: float  (must be in [0.0, 1.0])
# result.requires_calibration: bool
```

**Invariants:** `MIRROR-0`, `MIRROR-DETERM-0`, `MIRROR-AUDIT-0`

---

### `EpochMemoryStore`
Ledger-backed epoch memory. Stores and retrieves memory entries across evolutionary epochs with append-only integrity guarantees.

```python
store = EpochMemoryStore(state_dir=Path(".adaad/memory"))
store.append(epoch_id="epoch-001", payload={"signal": 0.87})
entries = store.read(epoch_id="epoch-001")
```

**Invariants:** `MMEM-0`, `MMEM-CHAIN-0`, `MMEM-READONLY-0`

---

### `verify_ledger(ledger_path) -> dict`
Verifies every chain link in a JSONL ledger file. Fail-closed: raises `DASVerifyError` on first broken link.

```python
from adaad_core import verify_ledger
result = verify_ledger("artifacts/governance/phase121/audit.jsonl")
# result: {"ok": True, "records_checked": 42, "error": None}
```

**Invariants:** `DAS-VERIFY-0`

---

## Invariant Registry (CORE-level)

| ID | Description |
|---|---|
| `CORE-EXPORT-0` | All six symbols must be importable via `from adaad_core import ...` |
| `CORE-IMPORT-0` | Import must not trigger Aponi UI, SPIE, or federation module init |
| `CORE-SEMVER-0` | Breaking API changes require major version bump and HUMAN-0 ratification |

---

## Version History

| Version | Phase | Notes |
|---|---|---|
| 9.57.0 | 124 | Initial extraction — semver governance begins |

---

*This document is governed by `docs/CONSTITUTION.md`. API amendments require HUMAN-0 sign-off.*
