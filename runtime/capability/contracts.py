# SPDX-License-Identifier: Apache-2.0
"""
runtime.capability.contracts
=============================
The initial 10 capability contracts for ADAAD v8.

Approved by: Dustin L. Reid  (CAP-REGISTRY gate — Phase 59)
Gate:        HUMAN-0 / CAP-REGISTRY

These are the foundational capability contracts that form the constitutional
identity layer of the ADAAD mutation engine.  Every entry is registered into
the module-level BOOTSTRAP_REGISTRY on import.

Capability Index
----------------
1.  governance.gate          Tier-0  GovernanceGate enforcement
2.  governance.policy        Tier-0  Policy artifact loading
3.  determinism.provider     Tier-0  RuntimeDeterminismProvider
4.  evolution.loop           Tier-1  EvolutionLoop orchestration
5.  evolution.proposal       Tier-1  ProposalEngine + auto-provisioning
6.  mutation.code_intel      Tier-1  Code Intelligence Layer (Phase 58)
7.  mutation.history         Tier-1  MutationHistory ledger
8.  intelligence.critique    Tier-1  CritiqueSignalBuffer
9.  intelligence.telemetry   Tier-1  RoutedDecisionTelemetry
10. scoring.ledger           Tier-1  ScoringLedgerStore
"""

from __future__ import annotations

from typing import List

from runtime.capability.capability_node import CapabilityContract, CapabilityNode
from runtime.capability.capability_registry import CapabilityRegistry

# ---------------------------------------------------------------------------
# Canonical contract definitions
# ---------------------------------------------------------------------------

_CONTRACT_SPECS: List[dict] = [
    # 1 — governance.gate  (Tier-0)
    {
        "capability_id": "governance.gate",
        "version": "8.1.0",
        "contract": CapabilityContract(
            description=(
                "Sole mutation approval surface. Every proposed code mutation "
                "must pass through GovernanceGate before application. "
                "Fail-closed: gate default is rejection."
            ),
            preconditions=[
                "GATE-0: GovernanceGate is the only approval surface",
                "DET-0: approval decisions are deterministic and replayable",
            ],
            postconditions=[
                "Approved mutations carry a signed governance token",
                "Rejected mutations emit a GOVERNANCE_REJECTED telemetry event",
            ],
            tier=0,
            sla_max_ms=500,
        ),
        "governance_tags": frozenset({"GATE-0", "DET-0", "FAIL-CLOSED"}),
        "bound_modules": ["runtime/governance/gate.py"],
        "dependency_set": frozenset(),
    },
    # 2 — governance.policy  (Tier-0)
    {
        "capability_id": "governance.policy",
        "version": "8.1.0",
        "contract": CapabilityContract(
            description=(
                "Loads and validates the governance policy artifact. "
                "Provides state_backend, constitution version, and penalty caps."
            ),
            preconditions=["Policy artifact must exist at GOVERNANCE_POLICY_PATH"],
            postconditions=["Loaded policy is immutable for the duration of the epoch"],
            tier=0,
            sla_max_ms=200,
        ),
        "governance_tags": frozenset({"POLICY-0", "IMMUTABLE-EPOCH"}),
        "bound_modules": ["runtime/governance/policy_artifact.py"],
        "dependency_set": frozenset(),
    },
    # 3 — determinism.provider  (Tier-0)
    {
        "capability_id": "determinism.provider",
        "version": "8.1.0",
        "contract": CapabilityContract(
            description=(
                "RuntimeDeterminismProvider: sole source of timestamps, UUIDs, "
                "and RNG seeds. All callers must use this provider; direct "
                "datetime.now() / uuid4() / random.random() are forbidden."
            ),
            preconditions=[
                "PYTHONHASHSEED must not seed any RNG (use hashlib.sha256)",
                "Provider must be injectable for deterministic replay",
            ],
            postconditions=[
                "now_utc() returns ISO-8601 UTC string with Z suffix",
                "All generated values are logged for replay verification",
            ],
            tier=0,
            sla_max_ms=10,
        ),
        "governance_tags": frozenset({"DET-0", "REPLAY-0", "NO-HASH-SEED"}),
        "bound_modules": ["runtime/determinism.py"],
        "dependency_set": frozenset(),
    },
    # 4 — evolution.loop  (Tier-1)
    {
        "capability_id": "evolution.loop",
        "version": "8.1.0",
        "contract": CapabilityContract(
            description=(
                "EvolutionLoop: primary epoch orchestration surface. "
                "Calls ProposalEngine, evaluates fitness, applies governed mutations."
            ),
            preconditions=[
                "GovernanceGate must be initialised before epoch start",
                "DeterminismProvider must be injected",
            ],
            postconditions=[
                "Each epoch emits EpochTelemetry",
                "No mutation applied without governance token",
            ],
            tier=1,
            sla_max_ms=30_000,
        ),
        "governance_tags": frozenset({"EPOCH-0", "GOVERNED-MUTATION"}),
        "bound_modules": ["runtime/evolution/evolution_loop.py"],
        "dependency_set": frozenset({"governance.gate", "determinism.provider"}),
    },
    # 5 — evolution.proposal  (Tier-1)
    {
        "capability_id": "evolution.proposal",
        "version": "8.1.0",
        "contract": CapabilityContract(
            description=(
                "ProposalEngine + auto-provisioning (Phase 57). "
                "Generates code mutation proposals enriched with strategy context. "
                "Auto-provisions when ADAAD_ANTHROPIC_API_KEY is present."
            ),
            preconditions=[
                "PROP-AUTO-0: engine is default-on when API key present",
                "All proposals enter the governed pipeline — no bypass",
            ],
            postconditions=[
                "Proposal carries confidence score and strategy_id",
                "LLM fallback_to_noop=False when key is set",
            ],
            tier=1,
            sla_max_ms=10_000,
        ),
        "governance_tags": frozenset({"PROP-AUTO-0", "NO-BYPASS"}),
        "bound_modules": ["runtime/evolution/evolution_loop.py"],
        "dependency_set": frozenset({"evolution.loop", "governance.gate"}),
    },
    # 6 — mutation.code_intel  (Tier-1)
    {
        "capability_id": "mutation.code_intel",
        "version": "8.1.0",
        "contract": CapabilityContract(
            description=(
                "Code Intelligence Layer (Phase 58). Provides FunctionCallGraph, "
                "HotspotMap, MutationHistory, and CodeIntelModel frozen snapshots "
                "for ProposalEngine enrichment."
            ),
            preconditions=[
                "INTEL-ISO-0: no governance/ledger imports inside code_intel/",
                "INTEL-DET-0: all hashes via sha256(json.dumps(., sort_keys=True))",
                "INTEL-TS-0: all timestamps via RuntimeDeterminismProvider.now_utc()",
            ],
            postconditions=[
                "CodeIntelModel is frozen and immutable after build()",
                "model_hash binds the full snapshot state",
            ],
            tier=1,
            sla_max_ms=5_000,
        ),
        "governance_tags": frozenset({"INTEL-ISO-0", "INTEL-DET-0", "INTEL-TS-0"}),
        "bound_modules": [
            "runtime/mutation/code_intel/function_graph.py",
            "runtime/mutation/code_intel/hotspot_map.py",
            "runtime/mutation/code_intel/mutation_history.py",
            "runtime/mutation/code_intel/code_intel_model.py",
        ],
        "dependency_set": frozenset({"determinism.provider"}),
    },
    # 7 — mutation.history  (Tier-1)
    {
        "capability_id": "mutation.history",
        "version": "8.1.0",
        "contract": CapabilityContract(
            description=(
                "MutationHistory: append-only hash-chained JSONL ledger of all "
                "code mutation events. Provides churn signals to HotspotMap."
            ),
            preconditions=[
                "Records are append-only — no deletions or updates",
                "Prior-hash chain must verify end-to-end",
            ],
            postconditions=[
                "verify_integrity() returns True after every append",
                "IntegrityError raised if chain is broken",
            ],
            tier=1,
            sla_max_ms=100,
        ),
        "governance_tags": frozenset({"APPEND-ONLY", "HASH-CHAIN", "INTEL-TS-0"}),
        "bound_modules": ["runtime/mutation/code_intel/mutation_history.py"],
        "dependency_set": frozenset({"mutation.code_intel", "determinism.provider"}),
    },
    # 8 — intelligence.critique  (Tier-1)
    {
        "capability_id": "intelligence.critique",
        "version": "8.1.0",
        "contract": CapabilityContract(
            description=(
                "CritiqueSignalBuffer: aggregates penalty signals from Architect, "
                "Dream, and Beast agents. Penalty cap enforced at 0.20."
            ),
            preconditions=[
                "Penalty cap: no single critique signal may exceed 0.20",
                "Buffer is bounded; oldest signals evicted on overflow",
            ],
            postconditions=[
                "Aggregated penalty is in [0.0, 0.20]",
                "All signals carry agent_id and timestamp",
            ],
            tier=1,
            sla_max_ms=50,
        ),
        "governance_tags": frozenset({"PENALTY-CAP-0.20", "AGENT-SIGNAL"}),
        "bound_modules": ["runtime/intelligence/__init__.py"],
        "dependency_set": frozenset({"determinism.provider"}),
    },
    # 9 — intelligence.telemetry  (Tier-1)
    {
        "capability_id": "intelligence.telemetry",
        "version": "8.1.0",
        "contract": CapabilityContract(
            description=(
                "RoutedDecisionTelemetry + InMemoryTelemetrySink: structured "
                "routing of intelligence decisions for observability."
            ),
            preconditions=[
                "Every routed decision emits EVENT_TYPE_ROUTED_INTELLIGENCE_DECISION",
            ],
            postconditions=[
                "Sink retains events in FIFO order for replay",
                "All events carry timestamp from determinism provider",
            ],
            tier=1,
            sla_max_ms=20,
        ),
        "governance_tags": frozenset({"TELEMETRY-0", "REPLAY-0"}),
        "bound_modules": ["runtime/intelligence/__init__.py"],
        "dependency_set": frozenset({"intelligence.critique", "determinism.provider"}),
    },
    # 10 — scoring.ledger  (Tier-1)
    {
        "capability_id": "scoring.ledger",
        "version": "8.1.0",
        "contract": CapabilityContract(
            description=(
                "ScoringLedgerStore: durable append-only scoring record. "
                "Stores epoch fitness scores with hash-chain integrity."
            ),
            preconditions=[
                "Scores are immutable once committed",
                "Hash chain must be verifiable end-to-end",
            ],
            postconditions=[
                "Every committed score carries a prior_hash link",
                "Ledger digest is deterministic given same inputs",
            ],
            tier=1,
            sla_max_ms=100,
        ),
        "governance_tags": frozenset({"APPEND-ONLY", "HASH-CHAIN", "DET-0"}),
        "bound_modules": ["runtime/state/scoring_ledger.py"],
        "dependency_set": frozenset({"determinism.provider"}),
    },
]


# ---------------------------------------------------------------------------
# Bootstrap registry — built once at module import
# ---------------------------------------------------------------------------

def build_bootstrap_registry() -> CapabilityRegistry:
    """Construct and return a CapabilityRegistry with all 10 base contracts."""
    registry = CapabilityRegistry()

    for spec in _CONTRACT_SPECS:
        node = CapabilityNode(
            capability_id=spec["capability_id"],
            version=spec["version"],
            contract=spec["contract"],
            governance_tags=spec["governance_tags"],
            bound_modules=spec["bound_modules"],
            dependency_set=spec["dependency_set"],
        )
        ok, reason = registry.register(node)
        if not ok:
            raise RuntimeError(
                f"Bootstrap capability registration failed for "
                f"'{spec['capability_id']}': {reason}"
            )

    return registry


# Module-level singleton — importable directly
BOOTSTRAP_REGISTRY: CapabilityRegistry = build_bootstrap_registry()
