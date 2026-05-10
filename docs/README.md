<div align="center">

<img src="assets/adaad-banner.svg" width="100%" alt="ADAAD — Autonomous Development &amp; Adaptation Architecture"/>

<br/>

[![Version](https://img.shields.io/badge/ADAAD-v9.111.0-000?style=for-the-badge&labelColor=0d1117&color=00d4ff)](../CHANGELOG.md)&nbsp;[![Phase](https://img.shields.io/badge/Phase_177-IIS_Shipped-000?style=for-the-badge&labelColor=0d1117&color=f5c842)](../ROADMAP.md)&nbsp;[![Constitution](https://img.shields.io/badge/Constitution-v0.9.0_%C2%B7_23_Rules-000?style=for-the-badge&labelColor=0d1117&color=ff4466)](CONSTITUTION.md)&nbsp;[![Tests](https://img.shields.io/badge/4%2C624_Tests-Passing-000?style=for-the-badge&labelColor=0d1117&color=00ff88)](../tests/)

<br/>

[Architecture](#architecture-overview) &nbsp;·&nbsp; [CEL 14-Step](#constitutional-evolution-loop) &nbsp;·&nbsp; [API Reference](#module-api-reference) &nbsp;·&nbsp; [Config](#configuration-reference) &nbsp;·&nbsp; [Evidence](#evidence-artifacts) &nbsp;·&nbsp; [Tests](#test-coverage-matrix) &nbsp;·&nbsp; [Index](#documentation-index)

</div>

<img src="assets/adaad-section-divider.svg" width="100%" style="opacity:0.72;" alt=""/>

> Internal architecture, API contracts, configuration, evidence artifacts, and test coverage for **ADAAD v9.106.0 · Phase 173 (INNOV-79 Innovation Impact Scorer (IIS) shipped)**. For user-facing setup see [QUICKSTART.md](../QUICKSTART.md). For the 23 rules see [CONSTITUTION.md](CONSTITUTION.md). For build-agent protocol see [AGENTS.md](../AGENTS.md).
>
> **Last reviewed:** 2026-05-08
> **Current/Next:** Current = Phase 173 (v9.106.0), Next = Phase 174 — next non-shipped innovation.

<br/>

## Documentation Index

<details open>
<summary><strong>🏛 Governance &amp; Architecture</strong></summary>

<br/>

| Document | Purpose | Status |
|:---|:---|:---:|
| [CONSTITUTION.md](CONSTITUTION.md) | 23 constitutional rules — root of all authority | 🟢 v0.9.0 |
| [ARCHITECTURE_CONTRACT.md](ARCHITECTURE_CONTRACT.md) | Structural constraints, 8 invariants, module ownership | 🟢 Live |
| [governance/ARCHITECT_SPEC_v3.1.0.md](governance/ARCHITECT_SPEC_v3.1.0.md) | Canonical implementation spec — all organ contracts | 🟢 Current |
| [governance/V8_CONSTITUTIONAL_INVARIANTS_MATRIX.md](governance/V8_CONSTITUTIONAL_INVARIANTS_MATRIX.md) | Invariant enforcement matrix with test bindings | 🟢 Live |
| [governance/LLM_FAILOVER_CONTRACT.md](governance/LLM_FAILOVER_CONTRACT.md) | LLM provider failover governance (Phase 91 baseline) | 🟢 v9.1 |
| [governance/KEY_CEREMONY_RUNBOOK_v1.md](governance/KEY_CEREMONY_RUNBOOK_v1.md) | 2-of-3 Ed25519 key ceremony procedure (Phase 91 baseline) | 🟢 v9.1 |
| [SECURITY.md](SECURITY.md) | Security posture, threat model summary | 🟢 Live |
| [THREAT_MODEL.md](THREAT_MODEL.md) | Full threat model — attack surface analysis | 🟢 Live |

</details>

<details>
<summary><strong>⚙️ Runtime &amp; Operations</strong></summary>

<br/>

| Document | Purpose |
|:---|:---|
| [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) | Complete environment variable reference |
| [DETERMINISM.md](DETERMINISM.md) | Determinism contract — how `DET-ALL-0` is enforced |
| [governance/DETERMINISM_CONTRACT_SPEC.md](governance/DETERMINISM_CONTRACT_SPEC.md) | Technical spec for replay attestation |
| [governance/entropy_budget.md](governance/entropy_budget.md) | Entropy budget limits and monitoring |
| [governance/mutation_lifecycle.md](governance/mutation_lifecycle.md) | Full mutation lifecycle state machine |
| [governance/ledger_event_contract.md](governance/ledger_event_contract.md) | EpochEvidence ledger event schema v1 |
| [governance/fail_closed_recovery_runbook.md](governance/fail_closed_recovery_runbook.md) | Fail-closed recovery procedures |
| [governance/APONI_ALERT_RUNBOOK.md](governance/APONI_ALERT_RUNBOOK.md) | Aponi alert triage and escalation paths |

</details>

<details>
<summary><strong>🧪 Testing &amp; Quality</strong></summary>

<br/>

| Document | Purpose |
|:---|:---|
| [governance/BENCHMARK_SPEC.md](governance/BENCHMARK_SPEC.md) | Fitness benchmark specification and acceptance criteria |
| [governance/test_marker_taxonomy.md](governance/test_marker_taxonomy.md) | pytest mark taxonomy — `autonomous_critical`, `governance`, etc. |
| [governance/STRICT_REPLAY_INVARIANTS.md](governance/STRICT_REPLAY_INVARIANTS.md) | Replay invariant contracts for test suite |
| [testing/monolith_test_domain_mapping.md](testing/monolith_test_domain_mapping.md) | Test file to module domain mapping |
| [governance/fitness_spec_v1.md](governance/fitness_spec_v1.md) | FitnessEngine v1 specification (reference for v2 delta) |
| [comms/repo_deep_audit_thesis_2026-03-28.md](comms/repo_deep_audit_thesis_2026-03-28.md) | Latest full audit/thesis deep-run execution snapshot and gate outcomes |

</details>

<details>
<summary><strong>📡 Federation &amp; Security</strong></summary>

<br/>

| Document | Purpose |
|:---|:---|
| [governance/FEDERATION_KEY_REGISTRY.md](governance/FEDERATION_KEY_REGISTRY.md) | Federation HMAC key registry and rotation procedures |
| [governance/FEDERATION_CONFLICT_RUNBOOK.md](governance/FEDERATION_CONFLICT_RUNBOOK.md) | Cross-repo mutation conflict resolution |
| [protocols/v1/federation_handshake.md](protocols/v1/federation_handshake.md) | Federation handshake protocol v1 |
| [governance/control_plane_auth.md](governance/control_plane_auth.md) | Control plane authentication contracts |
| [governance/SECURITY_INVARIANTS_MATRIX.md](governance/SECURITY_INVARIANTS_MATRIX.md) | Security invariants with enforcement mapping |
| [governance/POLICY_ARTIFACT_SIGNING_GUIDE.md](governance/POLICY_ARTIFACT_SIGNING_GUIDE.md) | Policy artifact signing with Ed25519 |

</details>

<details>
<summary><strong>🧭 Strategy &amp; Universe Alignment</strong></summary>

<br/>

| Document | Purpose |
|:---|:---|
| [INNOVATIVEAI_UNIVERSE_ALIGNMENT.md](INNOVATIVEAI_UNIVERSE_ALIGNMENT.md) | Repository-native alignment map for ADAAD, InnovativeArtsInc, JRT, Shame Tapestry / MVNA, hub routing, enhancement backlog, and optimization scorecard |

</details>

<details>
<summary><strong>📋 Release History</strong></summary>

<br/>

| Release | Theme | Notes |
|:---:|:---|:---|
| [9.1.0](releases/9.0.0.md) | Hardening Tier Alpha | Phase 91 — audit hardening, telemetry, lineage invariants, governance contracts |
| [9.0.0](releases/9.0.0.md) | Emergence | Phase 65 — First Autonomous Self-Evolution |
| [8.4.0](releases/8.4.0.md) | Lineage | Phase 61 — Lineage Engine + CompatibilityGraph |
| [7.x](releases/) | Scale & Resilience | Phases 31–50 — Cryovant, Aponi, federation hardening |

</details>

<br/>

<img src="assets/adaad-section-divider.svg" width="100%" style="opacity:0.72;" alt=""/>

## Replay CLI Namespace

Use the replay namespace for machine-readable deterministic replay workflows:

```bash
python -m app.main replay verify --epoch epoch-42 --mode strict
python -m app.main replay manifest --epoch epoch-42 --output adaad/replay/manifests/epoch-42.json
python -m app.main replay divergence-report --epoch epoch-42 --mode audit
python -m app.main replay bundle --pr-id PR-PHASE65-01
```

Each command prints canonical JSON so CI and governance automation can consume output without table parsing.

## Architecture Overview

<div align="center">
<img src="assets/adaad-architecture.svg" width="100%" alt="ADAAD System Architecture"/>
</div>

<br/>

ADAAD is organized into five independently testable subsystems, each with formal invariant bindings:

| Subsystem | Path | Invariant | Role |
|:---|:---|:---:|:---|
| 🧬 **Evolution Engine** | `runtime/evolution/` | `CEL-ORDER-0` | Constitutional Evolution Loop, lineage, fitness |
| 🚦 **Governance** | `runtime/governance/` | `GOV-SOLE-0` | GovernanceGate, 23 rules, federation, rate limiting |
| 🔬 **Mutation** | `runtime/mutation/` | `PATCH-SIZE-0` | AST substrate, SandboxTournament, CodeIntelModel |
| 🧠 **Autonomy** | `runtime/autonomy/` | `FIT-BOUND-0` | UCB1 bandit, AdaptiveWeights, NonStationarityDetector |
| 🔒 **Security** | `security/` | `TIER0-SELF-0` | Cryovant auth, key management, session governance |

### Subsystem Interaction Map

```
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                        ADAAD v9.106.0 Runtime                              │
  │                                                                         │
  │   ┌──────────┐                                                          │
  │   │ Architect│──┐                    ┌─────────────────┐                │
  │   └──────────┘  │  UCB1 Bandit       │  FitnessEngine  │                │
  │   ┌──────────┐  ├─► ProposalEngine ──►    v2 · 7 sig   │                │
  │   │  Dream   │──┤    12 candidates   │  adaptive wts   │                │
  │   └──────────┘  │    BLX-alpha       └────────┬────────┘                │
  │   ┌──────────┐  │    crossover                │ score                   │
  │   │  Beast   │──┘                             │                         │
  │   └──────────┘          AST patch             │                         │
  │                               ▼               ▼                         │
  │               ┌───────────────────────────────────────────┐             │
  │               │       Constitutional Evolution Loop        │             │
  │               │       14 steps · strict order · CEL-ORDER-0│             │
  │               └───────────────────┬───────────────────────┘             │
  │                                   │                                     │
  │               ┌───────────────────▼───────────────────────┐             │
  │               │             GovernanceGate                 │◄ GOV-SOLE-0│
  │               │    23 constitutional rules · non-bypassable│             │
  │               └───────────────────┬───────────────────────┘             │
  │                                   │ APPROVED                            │
  │              ┌────────────────────┼────────────────────┐                │
  │              ▼                    ▼                    ▼                │
  │     EvolutionLedger       CapabilityGraph         LineageLedger         │
  │     SHA-256 chain         version graph           stability DAG         │
  │     append-only           INTEL-DET-0             LINEAGE-STAB-0        │
  └─────────────────────────────────────────────────────────────────────────┘
```

<br/>

<img src="assets/adaad-section-divider.svg" width="100%" style="opacity:0.72;" alt=""/>

## Constitutional Evolution Loop

All 14 steps execute in strict declared sequence. Invariant **`CEL-ORDER-0`**: the order is structural, not configurable. One failure → clean halt. Zero silent errors.

<div align="center">
<img src="assets/adaad-flow.svg" width="100%" alt="ADAAD Mutation Flow — 14-step CEL sequence"/>
</div>

<br/>

| Step | Name | Type | Halt Condition |
|:---:|:---|:---:|:---|
| `01` | `MODEL-DRIFT-CHECK` | 🛡 Guard | Determinism state stale — block epoch |
| `02` | `LINEAGE-SNAPSHOT` | 📸 Capture | Records `capability_graph_before` hash |
| `03` | `FITNESS-BASELINE` | 📏 Measure | Pre-epoch 7-signal composite recorded |
| `04` | `PROPOSAL-GENERATE` | 🧬 Generate | LLM proposals — Architect / Dream / Beast |
| `05` | `AST-SCAN` | 🔍 Preflight | StaticSafetyScanner — 4 hard AST rules |
| `06` | `SANDBOX-EXECUTE` | 🧪 Test | Ephemeral clone — `SANDBOX_ONLY` flag respected |
| `07` | `REPLAY-VERIFY` | ✅ Verify | Hash mismatch — auto-rollback (`SANDBOX-DIV-0`) |
| `08` | `FITNESS-SCORE` | 📊 Score | Determinism divergence — unconditional veto |
| `09` | `GOVERNANCE-GATE-V2` | 🚦 Gate | 5 diff-aware AST rules (Phase 63 — Class A/B) |
| `10` | `GOVERNANCE-GATE` | 🚦 Gate | **23 constitutional rules — all must pass** |
| `11` | `LINEAGE-REGISTER` | 📝 Register | Survivors chained into lineage DAG |
| `12` | `PROMOTION-DECISION` | 🏆 Promote | `CapabilityGraph` + `PromotionEvent` recorded |
| `13` | `EPOCH-EVIDENCE` | 🔐 Seal | SHA-256 hash-chained ledger entry — immutable |
| `14` | `STATE-ADVANCE` | ⏭ Advance | Epoch counter + `epoch_complete.v1` event emitted |

> `ADAAD_SANDBOX_ONLY=true` runs all 14 steps — full evaluation, fitness scoring, gate checking — **with zero writes**. Always start here.

<br/>

<img src="assets/adaad-section-divider.svg" width="100%" style="opacity:0.72;" alt=""/>

## Module API Reference

<details open>
<summary><strong><code>runtime/evolution/evolution_loop.py</code> — Epoch orchestrator</strong></summary>

<br/>

```python
class EvolutionLoop:

    def run_epoch(context: EpochContext) -> EpochResult:
        """
        Routes to _run_cel_epoch() when ADAAD_CEL_ENABLED=true,
        otherwise to _run_legacy_epoch() (Phase 64 and prior).
        """

    def _run_cel_epoch(context: EpochContext) -> EpochResult:
        """
        Builds LiveWiredCEL, runs all 14 steps in strict order,
        extracts promoted IDs, calls _emit_capability_changes(),
        wraps result into EpochResult.
        Invariant: CEL-ORDER-0 — steps never skipped or reordered.
        """

    def _emit_capability_changes(
        promoted_ids: list[str],
        epoch_evidence_hash: str
    ) -> None:
        """
        Fail-safe. Writes CapabilityChange entries to CapabilityGraph.
        Exceptions logged and swallowed — never propagated.
        Zero blast radius on ledger write failures.
        """


@dataclass
class EpochResult:
    epoch_id: str
    promoted_ids: list[str]
    evidence_hash: str
    fitness_composite: float
    cel_result: Optional[object] = None   # Added Phase 65
```

</details>

<details>
<summary><strong><code>runtime/capability_graph.py</code> — Capability lineage ledger</strong></summary>

<br/>

```python
@dataclass
class CapabilityChange:
    node_id: str                  # capability node being changed
    old_version: str              # semver before mutation
    new_version: str              # semver after mutation
    epoch_evidence_hash: str      # SHA-256 of the epoch evidence record
    proposal_hash: str            # SHA-256 of the winning proposal
    timestamp: str                # ISO-8601 UTC

    @property
    def change_id(self) -> str:
        # SHA-256[:16] of "node_id:proposal_hash:epoch_evidence_hash"
        # Deterministic — identical inputs produce identical IDs (INTEL-DET-0)

    def to_dict(self) -> dict:
        # Returns ledger-ready record including change_id


def record_capability_change(
    change: CapabilityChange,
    ledger_path: Path = Path("data/capability_changes.jsonl")
) -> str:
    """
    Appends JSONL to ADAAD_CAP_CHANGE_LEDGER.
    Fail-safe on IOError. Returns SHA-256 digest of appended record.
    """


class CapabilityGraph:
    def __init__(self, ledger_path: Path = ...) -> None
    def record_change(self, change: CapabilityChange) -> str
        # Delegates to record_capability_change()
```

</details>

<details>
<summary><strong><code>runtime/governance/governance_gate.py</code> — Constitutional enforcement</strong></summary>

<br/>

```python
class GovernanceGate:
    """
    Sole mutation approval surface. Invariant: GOV-SOLE-0.
    Cannot be bypassed via config, env var, or any code path.
    """

    def approve(self, patch: ASTDiffPatch) -> GovernanceDecision:
        """
        Evaluates all 23 constitutional rules against the patch.
        Returns APPROVED only if ALL rules pass.
        Returns REJECTED with blocking rule identifiers on any failure.
        Decision is deterministic — identical patch -> identical decision.
        """

    def evaluate_rule(self, rule_id: str, patch: ASTDiffPatch) -> RuleResult:
        """Returns PASS / WARN / BLOCK with reason string."""


class GovernanceGateV2:
    """
    Diff-aware AST gate (Phase 63). Classifies mutations as Class A or B.
    Class A (complexity delta <= +2): auto-approved if all rules pass.
    Class B (complexity delta > +2): requires exception token + HUMAN-0 co-sign.
    """

    def approve(self, patch: ASTDiffPatch) -> GateV2Decision:
        # Returns classification + approval status
```

</details>

<details>
<summary><strong><code>runtime/evolution/fitness_engine_v2.py</code> — 7-signal scoring</strong></summary>

<br/>

```python
class FitnessEngineV2:
    """
    Scores mutation proposals across 7 independent signals.
    Determinism divergence (FIT-DIV-0) is an unconditional veto —
    cannot be overridden by any weight, config, or governance exception.
    """

    SIGNALS = [
        "test_delta",            # coverage + failure reduction
        "complexity_delta",      # cyclomatic change
        "performance_delta",     # runtime benchmark delta
        "governance_compliance", # 10-epoch rolling
        "architectural_fitness", # coupling + centrality
        "determinism",           # replay divergence  <-- VETO signal
        "node_economy",          # net AST additions
    ]
    WEIGHT_BOUNDS = (0.05, 0.70)  # FIT-BOUND-0

    def score(self, patch: ASTDiffPatch, baseline: FitnessBaseline) -> FitnessScore:
        """
        Raises VetoError("FIT-DIV-0") if determinism_divergence > 0.
        Returns composite float in [0.0, 1.0].
        """

    def adapt_weights(self, telemetry: PostMergeTelemetry) -> None:
        """EMA momentum descent (LR=0.05). Bounded [0.05, 0.70]."""
```

| Signal | Weight Range | Veto |
|:---|:---:|:---:|
| 🧪 Test delta | `[0.05, 0.70]` | — |
| 🌀 Complexity delta | `[0.05, 0.70]` | — |
| ⚡ Performance delta | `[0.05, 0.70]` | — |
| 📊 Governance compliance | `[0.05, 0.70]` | — |
| 🏗 Architectural fitness | `[0.05, 0.70]` | — |
| 🔒 Determinism | `[0.05, 0.70]` | 🚨 ANY divergence |
| 🧹 Node economy | `[0.05, 0.70]` | — |

</details>

<details>
<summary><strong><code>runtime/tools/mutation_guard.py</code> — Patch application</strong></summary>

<br/>

```python
def apply_dna_mutation(agent_id: str, ops: list[dict]) -> dict:
    """
    Applies JSON-Patch ops to agent DNA file.

    UPSERT behaviour: if DNA file does not exist and all ops are
    "set"/"add"/"replace", bootstraps an empty {} DNA and proceeds.
    Non-upsert ops against missing files raise FileNotFoundError.

    Intermediate dict nodes are auto-vivified for set/add ops.

    Returns:
        {
            agent_id: str,
            parent_lineage: str,   # SHA-256 of pre-patch DNA
            child_lineage: str,    # SHA-256 of post-patch DNA
            checksum: str,         # SHA-256 of applied patch ops
            applied: list[str],    # successfully applied op paths
            skipped: list[str],    # ops skipped (upsert conditions)
        }
    """
```

</details>

<details>
<summary><strong><code>runtime/autonomy/bandit.py</code> — Agent selection</strong></summary>

<br/>

```python
class UCB1Bandit:
    """
    Selects among Architect, Dream, and Beast agents for epoch proposals.
    Invariant: BANDIT-ARM-0 — arm state must be consistent across replays.
    Switches to Thompson Sampling after >= 30 non-stationary epochs
    (detected by NonStationarityDetector via Page-Hinkley test).
    """

    def select_arm(self) -> str:
        """Returns agent_id: 'architect' | 'dream' | 'beast'"""

    def update(self, agent_id: str, reward: float) -> None:
        """EMA-weighted reward update. Triggers non-stationarity check."""


class AdaptiveWeights:
    """
    Adjusts FitnessEngine signal weights from post-merge telemetry.
    EMA descent (LR=0.05). Bounded [0.05, 0.70] (FIT-BOUND-0).
    prediction_accuracy published to epoch telemetry every cycle (v9.11.0).
    """
```

</details>

<br/>

<img src="assets/adaad-section-divider.svg" width="100%" style="opacity:0.72;" alt=""/>

## Configuration Reference

All environment variables are read at startup. No hot-reload. Changing variables requires process restart.

| Variable | Default | Required | Description |
|:---|:---:|:---:|:---|
| `ADAAD_CEL_ENABLED` | `false` | — | `true` activates 14-step Constitutional Evolution Loop |
| `ADAAD_SANDBOX_ONLY` | `false` | — | `true` runs full CEL with **zero writes** — dry-run mode |
| `ADAAD_ENV` | `dev` | — | `dev` · `staging` · `prod` — controls auth strictness |
| `ADAAD_DETERMINISTIC_LOCK` | `0` | — | `1` enforces deterministic-only execution paths |
| `ADAAD_CAP_CHANGE_LEDGER` | `data/capability_changes.jsonl` | — | Path for CapabilityChange JSONL ledger |
| `ADAAD_ANTHROPIC_API_KEY` | — | Prod | Enables live LLM proposals in ProposalEngine |
| `ADAAD_REPLAY_PROOF_HMAC_SECRET_PROOF_KEY` | — | Prod | HMAC secret for replay proof signing |
| `ADAAD_REPLAY_PROOF_PRIVATE_KEY_REPLAY_PROOF_ED25519_DEV` | — | Prod | Ed25519 private key for replay attestation |
| `CRYOVANT_DEV_MODE` | `0` | — | `1` bypasses Cryovant auth for local dev (never in prod) |

> **Production:** `ADAAD_ENV=prod` enforces all auth contracts. `CRYOVANT_DEV_MODE=1` in production is a critical security violation — detected and blocked by Cryovant middleware.

**Recommended dev startup:**

```bash
ADAAD_CEL_ENABLED=true \
ADAAD_SANDBOX_ONLY=true \
ADAAD_ENV=dev \
CRYOVANT_DEV_MODE=1 \
python app/main.py
```

<br/>

<img src="assets/adaad-section-divider.svg" width="100%" style="opacity:0.72;" alt=""/>

## Evidence Artifacts

Evidence bundles are written by `EpochEvidence` at CEL step 13. Every bundle is SHA-256 hash-chained to the previous — tamper-evident and append-only. Stored under `artifacts/governance/`.

| Phase | Bundle | Gate | Verdict |
|:---:|:---|:---:|:---:|
| **65** | `phase65/mutation_target_signoff.json` | `HUMAN-0` — mutation target selection | ✅ |
| **65** | `phase65/v9_release_audit_report.json` | `AUDIT-0` — 22/22 tests pass | ✅ |
| **65** | `phase65/v9_replay_verification.json` | `REPLAY-0` — 0 divergences | ✅ |
| **64** | `phase64/cel_dry_run_signoff.json` | `CEL-DRY-RUN` — all 14 steps dry-run verified | ✅ |
| **63** | `phase63/governance_gate_v2_signoff.json` | `GATE-V2-RULES` — GovernanceGateV2 accepted | ✅ |
| **59** | `phase59/capability_graph_v2_signoff.json` | `CAP-REGISTRY` — 10 bootstrap capabilities | ✅ |

**Phase 65 Proof Summary:**

```json
{
  "event":   "EPOCH_COMPLETE",
  "phase":   65,
  "version": "9.0.0",
  "date":    "2026-03-13",
  "proof": {
    "replay_divergences":   0,
    "governance_bypasses":  0,
    "retroactive_evidence": false,
    "silent_failures":      0
  }
}
```

<br/>

<img src="assets/adaad-section-divider.svg" width="100%" style="opacity:0.72;" alt=""/>

## Test Coverage Matrix

| Phase | Test Files | Tests | Domain |
|:---:|:---|:---:|:---|
| **57** | `tests/evolution/test_phase57_*.py` | 16 | ProposalEngine · `PROP-AUTO-0..5` |
| **58** | `tests/mutation/test_phase58_*.py` | 60 | CodeIntelModel · FunctionGraph · HotspotMap |
| **59** | `tests/capability/test_phase59_*.py` | 59 | CapabilityRegistry · Tier-0 guard |
| **60** | `tests/mutation/test_phase60_*.py` | 59 | ASTDiffPatch · StaticSafetyScanner · SandboxTournament |
| **61** | `tests/evolution/test_phase61_*.py` | 62 | LineageEngine · niches · epistasis |
| **62** | `tests/evolution/test_phase62_*.py` | ~50 | FitnessEngineV2 · `FIT-BOUND-0` |
| **63** | `tests/governance/test_phase63_*.py` | ~55 | GovernanceGateV2 · exception tokens |
| **64** | `tests/evolution/test_phase64_*.py` | ~45 | LiveWiredCEL · 14-step sequence |
| **65** | `tests/evolution/test_phase65_emergence.py` | 22 | CEL wiring · CapabilityChange · routing |
| **66** | `tests/evolution/test_phase66_*.py` | 25 | Telemetry contracts · lineage invariants |
| Determinism | `tests/determinism/` | 102 | Replay attestation · boot profile · `DET-ALL-0` |
| **Total** | **267 files** | **4,466** | Full suite — `PYTHONPATH=. pytest tests/ -q` |

**Run the full suite:**

```bash
PYTHONPATH=. python -m pytest tests/ -q --tb=short
```

**Run governance tests only:**

```bash
PYTHONPATH=. python -m pytest tests/governance/ tests/determinism/ -q -m "governance or determinism"
```

**Run boot preflight (always first):**

```bash
PYTHONPATH=. python -m pytest tests/test_boot_preflight.py -v
```

<br/>

<img src="assets/adaad-section-divider.svg" width="100%" style="opacity:0.72;" alt=""/>

## Phase Evolution Timeline

| Phase | Era | Key Milestone | Version |
|:---:|:---|:---|:---:|
| 1–2 | 🧱 Foundation | `GovernanceGate` · Evidence Ledger · SHA-256 hash-chaining | v1.0 |
| 3–4 | 🧠 Adaptive Intelligence | `AdaptiveWeights` EMA · `SemanticDiffEngine` AST analysis | v2.x |
| 5–6 | 🌐 Federation & Autonomy | Multi-repo federation · HMAC gating · roadmap self-amendment | v3.x |
| 7–8 | 🎓 Governance Calibration | Reviewer reputation · governance health dashboard | v3.2–3.3 |
| 9–20 | 🔩 Core Hardening | Admission control · rate limiting · entropy baselines | v4.x |
| 21–30 | ⛓ Evidence & Lineage | Gate decision ledger · lineage stability · compatibility graph | v5.x |
| 31–40 | ⚖️ Scale & Resilience | Bandit integrity · Cryovant auth · Aponi dashboard | v6.x |
| 41–50 | 🏗 SPA & Infrastructure | Cryovant gate middleware · defect sweep · federation hardening | v7.x–8.x |
| 51–56 | 💡 Intelligence Layer | Memory governance · learning signal isolation · `MEMORY-0` | v8.x |
| 57 | 🔑 Keystone | ProposalEngine auto-provisioning | v8.0 |
| 58 | 👁 Perception | CodeIntelModel — code intelligence layer | v8.1 |
| 59 | 🪪 Identity | CapabilityGraph v2 + CapabilityTargetDiscovery | v8.2 |
| 60 | 🦾 Motor | AST Mutation Substrate + SandboxTournament | v8.3 |
| 61 | 🧬 Evolution | Lineage Engine + CompatibilityGraph | v8.4 |
| 62 | 📈 Intelligence | MultiHorizon FitnessEngine v2 | v8.5 |
| 63 | ⚖️ Judgment | GovernanceGate v2 + Exception Tokens | v8.6 |
| 64 | 🪞 Selfhood | Constitutional Evolution Loop (CEL) + EpochEvidence | v8.7 |
| **65** | **⛓ Emergence** | **First Autonomous Self-Evolution — March 13, 2026** | **v9.0** |
| **66** | **🔐 Hardening Tier Alpha** | Telemetry completeness · lineage invariants · governance contracts | **v9.1** |

<br/>

<img src="assets/adaad-section-divider.svg" width="100%" style="opacity:0.72;" alt=""/>

## Project Structure

```
ADAAD/
├── app/                        # Orchestrator · agents · mutation cycle · FastAPI
│   └── agents/                 # Architect / Dream / Beast implementations
│
├── runtime/                    # Core engine — the constitutional machine
│   ├── evolution/              # CEL · lineage · fitness · replay verifier
│   ├── governance/             # GovernanceGate (23 rules) · federation · rate limiting
│   ├── autonomy/               # Bandit · AdaptiveWeights · NonStationarityDetector
│   ├── mutation/               # AST substrate · SandboxTournament · CodeIntelModel
│   └── sandbox/                # Ephemeral container execution · preflight checks
│
├── security/                   # Cryovant — auth · key management · session governance
│
├── tests/                      # 267 test files · 4,466 passing
│   ├── evolution/              # CEL · epoch · lineage tests
│   ├── governance/             # Gate · constitutional rule tests
│   ├── mutation/               # AST · sandbox · scanner tests
│   ├── capability/             # CapabilityGraph · registry tests
│   └── determinism/            # Replay · attestation · DET-ALL-0 tests
│
├── docs/                       # You are here
│   ├── README.md               # This file — developer reference
│   ├── CONSTITUTION.md         # 23 rules — root of all authority
│   ├── assets/                 # SVG banners · architecture diagrams
│   └── governance/             # Specs · runbooks · contracts
│
├── artifacts/                  # Per-phase evidence artifacts (immutable after close)
├── governance/                 # Constitutional rules · federation keys · attestations
├── ui/                         # Aponi governance console
├── android/                    # Android build · F-Droid · Obtainium · PWA
│
├── QUICKSTART.md               # 5-minute setup guide
├── AGENTS.md                   # Build agent protocol (ADAAD / DEVADAAD)
├── ROADMAP.md                  # Full phase roadmap
└── docs/CONSTITUTION.md        # The 23 rules — root of all authority
```

> `runtime/` is the canonical source tree. `build/lib/` is ephemeral packaging output — never commit as source. Generate build artifacts only in CI/release jobs.

<br/>

<img src="assets/adaad-section-divider.svg" width="100%" style="opacity:0.72;" alt=""/>

<div align="center">

[⚡ Quickstart](../QUICKSTART.md) &nbsp;·&nbsp; [📜 Constitution](CONSTITUTION.md) &nbsp;·&nbsp; [🗺 Roadmap](../ROADMAP.md) &nbsp;·&nbsp; [🤖 Agents](../AGENTS.md) &nbsp;·&nbsp; [📱 Android](../INSTALL_ANDROID.md) &nbsp;·&nbsp; [🏛 Arch Spec](governance/ARCHITECT_SPEC_v3.1.0.md) &nbsp;·&nbsp; [🔐 Evidence](comms/claims_evidence_matrix.md) &nbsp;·&nbsp; [🐛 Issues](https://github.com/InnovativeAI-adaad/ADAAD/issues)

<br/>

![version](https://img.shields.io/badge/ADAAD-v9.106.0-0d1117?style=flat-square&labelColor=0d1117&color=00d4ff)&nbsp;![phase](https://img.shields.io/badge/Phase_173-IIS_Shipped-0d1117?style=flat-square&labelColor=0d1117&color=f5c842)&nbsp;![constitution](https://img.shields.io/badge/Constitution-v0.9.0_%C2%B7_23_Rules-0d1117?style=flat-square&labelColor=0d1117&color=ff4466)&nbsp;![license](https://img.shields.io/badge/Apache_2.0-Free_Forever-0d1117?style=flat-square&labelColor=0d1117&color=00ff88)

<br/>

<sub><code>ADAAD v9.106.0</code> &nbsp;·&nbsp; Apache 2.0 &nbsp;·&nbsp; InnovativeAI LLC &nbsp;·&nbsp; Blackwell, Oklahoma &nbsp;·&nbsp; <a href="https://github.com/InnovativeAI-adaad/ADAAD">github.com/InnovativeAI-adaad/ADAAD</a></sub>

</div>
