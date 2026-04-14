# ADAAD Architecture Summary

**v9.48.0 · Phase 115 · 30 Innovations · 125 Hard-class Invariants**

*Canonical reference for technical evaluators, auditors, and integration partners.*

---

## System Identity

ADAAD (Autonomous Development & Adaptation Architecture) is a constitutionally governed autonomous code evolution runtime. It is not a code assistant. It is not CI/CD. It is a runtime that governs the process of AI self-evolution under formally encoded constitutional constraints with cryptographic provenance at every step.

**The core loop:** Propose → Adversarially Challenge → Score → Shadow Execute → Jury Evaluate → Governance Gate → Human Sign-off → Ledger Commit → Cryptographic Proof

---

## Architectural Layers

```
┌─────────────────────────────────────────────────────────────────────┐
│  HUMAN-0 Layer (HUMAN-0 invariant)                                  │
│  Dustin L. Reid · GPG key 4C95E2F99A775335B1CF3DAF247B015A1CCD95F6 │
│  Tier 0 mutations · Constitutional amendments · Release tags         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ GPG sign-off required
┌──────────────────────────────▼──────────────────────────────────────┐
│  Governance Layer                                                   │
│  GovernanceGateV2 · ConstitutionalJury · GovernanceGateV2          │
│  CEL-ORDER-0 · CJS-QUORUM-0 · CJS-DISSENT-0                        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ APPROVED verdict only
┌──────────────────────────────▼──────────────────────────────────────┐
│  Constitutional Evolution Loop (16 steps)                           │
│  MMEM Identity Check → Proposal → AFRT → Fitness → LSME → CJS →   │
│  GovernanceGate → Human → Ledger → Proof DAG → Dream Consolidation │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ Evidence-bound, hash-chained
┌──────────────────────────────▼──────────────────────────────────────┐
│  Innovations30 Layer (INNOV-COMPLETE-0)                             │
│  30 constitutional innovations · boot-gate enforced                 │
│  INNOV-01..30: all importable or RuntimeError (fail-closed)         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ Append-only JSONL
┌──────────────────────────────▼──────────────────────────────────────┐
│  Ledger Layer                                                       │
│  ScoringLedger · LineageLedgerV2 · GovernanceEventLedger           │
│  SHA-256 hash-chained · tamper-evident · independently verifiable   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## The 16-Step Constitutional Evolution Loop (CEL)

| Step | Name | Invariant | Description |
|:---:|:---|:---:|:---|
| 0a | EPOCH-INIT | `CEL-ORDER-0` | Epoch context initialized, determinism provider set |
| 0b | CONTEXT-BUILD | `CEL-ORDER-0` | `CodebaseContext` assembled |
| 0c | INTEL-SCAN | `AFRT-INTEL-0` | `CodeIntelModel` scanned for coverage gaps |
| 0d | IDENTITY-CHECK | `MMEM-0` | `IdentityContextInjector` fires; `identity_consistency_score` injected |
| 1 | PROPOSAL | `CEL-ORDER-0` | Agent (Architect/Dream/Beast) generates `MutationCandidate`s |
| 2 | RED-TEAM | `AFRT-0` | `AdversarialRedTeamAgent` generates adversarial cases |
| 3 | RED-TEAM-EXEC | `AFRT-CASES-0` | Cases executed in read-only sandbox; PASS or RETURNED |
| 4 | PROPOSAL-RESOLVE | `CEL-ORDER-0` | Seed proposal merged into context if present |
| 5 | LINEAGE-CHECK | `CEL-ORDER-0` | Lineage validity verified against `LineageLedgerV2` |
| 6 | FITNESS-SCORE | `FIT-BOUND-0` | `FitnessEngineV2` scores 8 signals; bounded [0.0, 1.0] |
| 7 | DETERMINISM-CHECK | `CEL-REPLAY-0` | Replay hash computed; divergence = hard block |
| 8 | SHADOW-EXEC | `LSME-0` | Zero-write shadow harness; real traffic; `ShadowFitnessReport` |
| 9 | PARETO-SELECT | `CEL-ORDER-0` | Pareto-optimal candidate selected |
| 10 | AFRT-GATE | `AFRT-GATE-0` | Red-team verdict enforced; RETURNED propagates |
| 11 | JURY-GATE | `CJS-0` | Constitutional jury convened for high-stakes paths |
| 12 | GOVERNANCE-GATE | `GOV-SOLE-0` | `GovernanceGateV2` evaluates full evidence package |
| 13 | LEDGER-COMMIT | `CEL-EVIDENCE-0` | Evidence hash-chained into append-only `ScoringLedger` |
| 14 | PROOF-DAG | `CEPD-0` | Merkle-rooted proof DAG updated |
| 15 | EPOCH-CLOSE | `CEL-ORDER-0` | Epoch result finalized; telemetry emitted |
| 16 | DREAM-CONSOLIDATION | `DSTE-0` | Cross-epoch dream candidates injected into next seed pool |

---

## Constitutional Hardening Pattern (Innovations30)

Every Innovations30 module follows this exact pattern — auditable by static analysis:

```python
# 1. Module-header invariant constant block
JURY_SIZE: int = 3
MAJORITY_REQUIRED: int = 2
HIGH_STAKES_PATHS: frozenset[str] = frozenset(["runtime/", "security/", "app/main.py"])

# 2. Typed gate violation exception (never bare Exception)
class ConstitutionalJuryConfigError(Exception):
    """Raised when jury_size < JURY_SIZE (CJS-QUORUM-0 misconfiguration)."""

# 3. Chain-linked ledger event dataclass
@dataclass
class JuryDecisionEvent:
    mutation_id: str
    verdict: str
    approve_count: int
    prev_event_hash: str        # ← chain integrity
    event_hash: str             # ← tamper detection via hmac.compare_digest

# 4. Append-only persistence — Path.open("a") only
def _persist(self, event: JuryDecisionEvent) -> None:
    self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with self.ledger_path.open("a") as f:   # ← never write_text
        f.write(json.dumps(dataclasses.asdict(event)) + "\n")

# 5. Deterministic digest — hashlib.sha256 only
decision_digest = "sha256:" + hashlib.sha256(
    f"{mutation_id}:{majority_verdict}:{approve_count}:{jury_size}".encode()
).hexdigest()

# 6. Security comparisons — hmac.compare_digest only
if not hmac.compare_digest(expected_hash, computed_hash):
    raise JuryQuorumError("Chain integrity violation")
```

A module that does not meet all 6 of these criteria is a **scaffold**, not a constitutionally hardened implementation. Scaffolds in production after their claimed phase are P1 findings.

---

## Invariant Enforcement Taxonomy

| Class | Count | Effect on violation | Example |
|:---|:---:|:---|:---|
| Hard-class | 125 | Epoch aborts; typed exception raised | `CJS-0`, `LSME-0`, `AFRT-0` |
| Constitutional-class | ~27 | Governance gate blocks; BLOCKED verdict | `GOV-SOLE-0`, `AST-IMPORT-0` |
| Advisory-class | variable | Logged; epoch continues; telemetry emitted | `REVIEW-PRESSURE-0` |

---

## Cryptographic Primitives

| Primitive | Usage | Invariant |
|:---|:---|:---:|
| SHA-256 | All ledger hashes, evidence digests, Merkle nodes | `CEL-EVIDENCE-0` |
| HMAC-SHA256 | Security comparisons (constant-time) | AUTH-CT-0 |
| GPG (Ed25519/RSA) | Release tags, Tier 0 governance events | `HUMAN-0` |
| Ed25519 2-of-3 | ✅ Executed 2026-04-12 on ADAADell | FINDING-66-004 resolved |

All cryptographic comparisons use `hmac.compare_digest` — short-circuit comparisons are prohibited and constitute a P0 finding.

---

## Dependency Surface

ADAAD's safety properties are grounded in the Python runtime and SHA-256 hash chains — not cloud infrastructure. Dependencies are deliberately minimal. See `requirements.txt` for the full surface. Key invariant: `AST-IMPORT-0` enforces import boundaries at PR gate, preventing unauthorized dependency surface expansion.

---

## Agent Architecture

Three Claude-powered agents compete per epoch via UCB1 multi-armed bandit:

| Agent | Strategy | Strength |
|:---|:---|:---|
| **Architect** | Structural reasoning | Maintainability, constitutional alignment |
| **Dream** | Exploratory mutation | Novel approaches, capability gap identification |
| **Beast** | Performance pressure | Throughput, efficiency, bottleneck elimination |

No single agent controls the outcome. The `AgentBanditSelector` routes based on prior epoch win/loss ratios. The governance gate is the only promotion authority. Agent Reputation Staking (INNOV-15) adds economic skin-in-the-game: agents stake credits on proposals; failed proposals burn stake.

---

## Ledger Architecture

```
security/ledger/
├── scoring.jsonl           ← All epoch governance decisions (hash-chained)
├── governance_events.jsonl ← HUMAN-0 sign-off events (hash-chained)
data/
├── jury_decisions.jsonl    ← CJS jury verdicts (hash-chained)
├── jury_decisions.dissent.jsonl  ← Dissenting verdicts (append-only)
├── genealogy_vectors.jsonl ← MGV property inheritance vectors
├── reputation_stakes.jsonl ← ARS stake records (append-only)
├── memory_transfers.jsonl  ← IMT cross-instance transfer log
```

Every ledger is:
- **Append-only:** `Path.open("a")` — no overwrites permitted
- **Hash-chained:** `prev_event_hash` on every record
- **Tamper-evident:** any altered entry breaks every subsequent hash
- **Deterministic:** identical input sequences produce identical hash sequences
- **Independently verifiable:** chain verification requires no system access beyond the JSONL file

---

*This document is maintained under the same constitutional governance as the system it describes. Amendments require ArchitectAgent approval, a CHANGELOG entry, and HUMAN-0 sign-off.*
