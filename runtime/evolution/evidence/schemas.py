# SPDX-License-Identifier: Apache-2.0
"""
ADAAD v8 Constitutional Evidence Substrate
==========================================
Five-pillar evidence stack for governed autonomous capability evolution.

CONSTITUTIONAL INVARIANTS ENFORCED:
  EVIDENCE-CHAIN-0  — every record is SHA-256 hash-chained; no retroactive modification
  EVIDENCE-DET-0    — all timestamps via RuntimeDeterminismProvider.now_utc()
  EVIDENCE-IMMU-0   — dataclasses are frozen; mutation raises FrozenInstanceError

Usage:
    from runtime.evolution.evidence.schemas import (
        EpochEvidence,
        MutationLineageEvidence,
        CapabilityVersionEvidence,
        GovernanceExceptionEvidence,
        ModelDriftEvidence,
        EvolutionEvidence,
    )
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class PromotionStatus(str, Enum):
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"
    QUARANTINED = "QUARANTINED"


class ResolutionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVERTED = "REVERTED"
    RESOLVED_AS_BENEFICIAL = "RESOLVED_AS_BENEFICIAL"


class DriftCatalyst(str, Enum):
    MUTATION_PROMOTION = "MUTATION_PROMOTION"
    MANUAL_REFACTOR = "MANUAL_REFACTOR"
    EPOCH_CONSOLIDATION = "EPOCH_CONSOLIDATION"
    ADVERSARIAL_CORRECTION = "ADVERSARIAL_CORRECTION"


# ---------------------------------------------------------------------------
# Pillar 1: EpochEvidence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EpochEvidence:
    """
    Master ledger entry for one full evolutionary cycle.
    Acts as the root hash for all epoch-level activity.

    CONSTITUTIONAL INVARIANT: EVIDENCE-CHAIN-0
    All fields serialize deterministically via compute_hash().
    predecessor_hash links this record to the prior epoch — chain is append-only.

    Field notes:
    - epoch_id           : UUID or chronological hash from EvolutionLoop.run_epoch()
    - model_hash_before  : SHA-256 of CodeIntelModel.__dict__ at epoch start
    - model_hash_after   : SHA-256 of CodeIntelModel.__dict__ at epoch end
    - capability_graph_before / after : SHA-256 of CapabilityGraph state
    - evaluated_lineages : all lineage_ids explored
    - promoted_lineage_id: winning lineage that passed GovernanceGate
    - replay_verification_hash: proof of deterministic execution (SANDBOX-DIV-0)
    - sandbox_container_id: hash/ID of ephemeral clone used — proves untampered env
    - predecessor_hash   : hash of prior EpochEvidence — breaks chain if tampered
    - timestamp          : MUST use RuntimeDeterminismProvider.now_utc()
    """
    epoch_id: str
    model_hash_before: str
    model_hash_after: str
    capability_graph_before: str
    capability_graph_after: str
    evaluated_lineages: tuple[str, ...]
    promoted_lineage_id: Optional[str]
    replay_verification_hash: str
    sandbox_container_id: str
    predecessor_hash: str
    timestamp: str

    # Derived evidence fields
    capability_targets: tuple[str, ...]       = field(default_factory=tuple)
    mutations_attempted: tuple[str, ...]      = field(default_factory=tuple)
    mutations_succeeded: tuple[str, ...]      = field(default_factory=tuple)
    governance_events: tuple[str, ...]        = field(default_factory=tuple)
    exception_tokens_used: tuple[str, ...]    = field(default_factory=tuple)
    fitness_summary: tuple[tuple[str, float], ...] = field(default_factory=tuple)
    adversarial_challenges_run: int           = 0
    adversarial_challenges_failed: int        = 0

    def compute_hash(self) -> str:
        """
        Deterministic SHA-256 of the full record.
        Used as predecessor_hash for the next EpochEvidence.
        Sorted-key JSON ensures field-order independence.
        """
        payload = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def validate_chain(self, prior: "EpochEvidence") -> bool:
        """Returns True if this record's predecessor_hash matches prior.compute_hash()."""
        return self.predecessor_hash == prior.compute_hash()


# ---------------------------------------------------------------------------
# Pillar 2: MutationLineageEvidence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MutationLineageEvidence:
    """
    Tracks the multi-step evolutionary trajectory of a mutation lineage.
    Proves how ADAAD moved from Point A to Point B across epochs.

    Field notes:
    - lineage_id              : unique ID for this evolutionary branch
    - parent_lineage_id       : the baseline this branch mutated from (None = root)
    - mutations_applied       : ordered tuple of mutation_ids in application order
    - fitness_trajectory      : delta in composite fitness score over lineage lifetime
    - stability_score         : 0.0..1.0; result from SandboxTournament isolation tests
    - governance_exceptions   : exception_token_ids used in this lineage (empty = clean)
    - promotion_status        : PROMOTED / REJECTED / QUARANTINED
    - epistasis_flags         : mutation_id pairs where A+B → regression; A and B alone pass
    - epochs_in_cooling       : number of epochs this lineage spent in cooling suspension
    """
    lineage_id: str
    parent_lineage_id: Optional[str]
    mutations_applied: tuple[str, ...]
    fitness_trajectory: float
    stability_score: float
    governance_exceptions_used: tuple[str, ...]
    promotion_status: PromotionStatus
    epistasis_flags: tuple[tuple[str, str], ...]  = field(default_factory=tuple)
    epochs_in_cooling: int                         = 0
    niche: str                                     = "unassigned"  # performance/architecture/safety/simplicity/experimental

    def is_clean(self) -> bool:
        """True if lineage completed without governance exceptions or epistasis."""
        return (
            len(self.governance_exceptions_used) == 0
            and len(self.epistasis_flags) == 0
        )

    def compute_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Pillar 3: CapabilityVersionEvidence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapabilityVersionEvidence:
    """
    Records every capability-level version change — the first-class unit of evolution.

    CONSTITUTIONAL INVARIANT: CAP-VERS-0
    Every capability version bump must be traceable to specific mutation hashes.
    Tier-0 capabilities (ConstitutionEnforcement, DeterministicReplay,
    LedgerEvidence, GovernanceGate) are never the target of version changes
    via autonomous mutation — enforced at GovernanceGate v2.

    Field notes:
    - capability_name         : must match CapabilityGraph.nodes key
    - version_from / to       : semantic versions (e.g. "1.2.0" → "1.3.0")
    - contract_delta_hash     : SHA-256 of the AST diff for public interfaces
    - bound_functions_mutated : functions altered to achieve the version bump
    - causal_mutation_hashes  : exact mutation_ids that forced this version bump
    - invariant_changes       : list of invariants added, removed, or modified
    - is_backward_compatible  : minor/patch bump = True; major bump = False
    - tier                    : "0" (immutable) or "1" (governed-mutable)
    """
    capability_name: str
    version_from: str
    version_to: str
    contract_delta_hash: str
    bound_functions_mutated: tuple[str, ...]
    causal_mutation_hashes: tuple[str, ...]
    invariant_changes: tuple[str, ...]
    is_backward_compatible: bool
    tier: str  # "0" | "1"
    epoch_id: str
    timestamp: str

    def validate_tier(self) -> None:
        """Raises ValueError if a Tier-0 capability is targeted by autonomous mutation."""
        TIER_0_CAPABILITIES = frozenset({
            "ConstitutionEnforcement",
            "DeterministicReplay",
            "LedgerEvidence",
            "GovernanceGate",
        })
        if self.capability_name in TIER_0_CAPABILITIES:
            raise ValueError(
                f"CONSTITUTIONAL VIOLATION: Tier-0 capability '{self.capability_name}' "
                f"may not be the target of an autonomous mutation. "
                f"Invariant: CAP-VERS-0."
            )

    def compute_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Pillar 4: GovernanceExceptionEvidence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GovernanceExceptionEvidence:
    """
    Records every temporary constitutional rule relaxation (Exception Token).
    Ensures exceptions are tracked, justified, strictly time-bounded, and human-co-signed.

    CONSTITUTIONAL INVARIANTS:
      HUMAN-0         — human must co-sign every exception; human_key_fingerprint required
      EXCEPTION-TTL-0 — max 3 epochs; non-renewable without new human gate
      EXCEPTION-SCOPE-0 — scoped to single capability; no blanket exceptions
      TIER0-EXCEPT-0  — Tier-0 capabilities ineligible for exceptions

    Field notes:
    - exception_token_id      : sha256(epoch_id + capability_name + rule_id + scope_hash)
    - target_capability       : capability allowed to temporarily bypass the rule
    - violated_rule           : MUST be "AST-COMPLEX-0" for Phase 63 scope
    - justification_trace     : chain-of-thought hash from Constitutional Dialogue
    - duration_epochs         : hard TTL; 1..3 inclusive; non-renewable
    - human_key_fingerprint   : PGP/SSH key fingerprint of approving human (HUMAN-0)
    - human_approval_ref      : HumanApprovalGate reference ID
    - resolution_status       : ACTIVE / REVERTED / RESOLVED_AS_BENEFICIAL
    - revocation_trigger      : auto-revoke condition that fired (None if not revoked)
    - lineage_projection      : fitness projections for +1, +2, +3 epochs
    - mutations_covered       : mutation_ids executed under this exception
    """
    exception_token_id: str
    target_capability: str
    violated_rule: str
    justification_trace: str
    duration_epochs: int
    human_key_fingerprint: str
    human_approval_ref: str
    granted_at_epoch: str
    expires_at_epoch: int
    resolution_status: ResolutionStatus
    lineage_projection: tuple[float, float, float]
    mutations_covered: tuple[str, ...]
    revocation_trigger: Optional[str]   = None

    ELIGIBLE_RULES: frozenset = frozenset({"AST-COMPLEX-0"})

    def validate(self) -> None:
        """Raises ValueError on any constitutional violation of the exception schema."""
        if self.violated_rule not in self.ELIGIBLE_RULES:
            raise ValueError(
                f"CONSTITUTIONAL VIOLATION: Only {self.ELIGIBLE_RULES} are "
                f"eligible for exceptions. Got: '{self.violated_rule}'."
            )
        if not 1 <= self.duration_epochs <= 3:
            raise ValueError(
                f"CONSTITUTIONAL VIOLATION (EXCEPTION-TTL-0): duration_epochs must "
                f"be 1..3. Got: {self.duration_epochs}."
            )
        TIER_0_CAPABILITIES = frozenset({
            "ConstitutionEnforcement", "DeterministicReplay",
            "LedgerEvidence", "GovernanceGate",
        })
        if self.target_capability in TIER_0_CAPABILITIES:
            raise ValueError(
                f"CONSTITUTIONAL VIOLATION (TIER0-EXCEPT-0): Tier-0 capability "
                f"'{self.target_capability}' is ineligible for exceptions."
            )
        if not self.human_key_fingerprint or not self.human_approval_ref:
            raise ValueError(
                "CONSTITUTIONAL VIOLATION (HUMAN-0): human_key_fingerprint and "
                "human_approval_ref are required for all exceptions."
            )

    def is_expired(self, current_epoch_count: int) -> bool:
        return current_epoch_count >= self.expires_at_epoch

    def compute_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Pillar 5: ModelDriftEvidence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelDriftEvidence:
    """
    Self-awareness integrity check for the Code Intelligence Layer.
    Ensures CodeIntelModel has not silently corrupted its understanding of the codebase.

    CONSTITUTIONAL INVARIANT: CODEINTEL-DET-0
    determinism_verified must be True before any epoch proceeds past Step 1.
    If False, epoch is blocked and a DRIFT-ALERT incident is written to the ledger.

    Field notes:
    - drift_event_id          : unique ID for this drift check event
    - function_graph_delta    : 0.0 = no change; 1.0 = complete structural overhaul
    - hotspot_map_shift       : 0.0 = no shift; 1.0 = all hotspots moved
    - mutation_history_delta  : change in mutation success-rate distribution
    - catalyst_event          : what triggered the drift (DriftCatalyst enum)
    - determinism_verified    : True if model produces identical graph on replay pass
    - model_hash_before / after: SHA-256 of CodeIntelModel at check boundaries
    - divergent_functions     : function names where extractor produced different results
    - lockdown_triggered      : True if drift exceeded threshold and system entered lockdown
    - drift_threshold         : configurable threshold (default 0.15 from static_rules.yaml)
    """
    drift_event_id: str
    function_graph_delta: float
    hotspot_map_shift: float
    mutation_history_delta: float
    catalyst_event: DriftCatalyst
    determinism_verified: bool
    model_hash_before: str
    model_hash_after: str
    divergent_functions: tuple[str, ...]
    lockdown_triggered: bool
    drift_threshold: float
    epoch_id: str
    timestamp: str

    def is_safe(self) -> bool:
        """
        Returns True if drift is within threshold and determinism verified.
        If False, the epoch MUST NOT proceed — block at Step 1 of CEL.
        """
        return (
            self.determinism_verified
            and self.function_graph_delta <= self.drift_threshold
            and not self.lockdown_triggered
        )

    def compute_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Unified Aggregator: EvolutionEvidence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvolutionEvidence:
    """
    Unified payload written to the append-only Lineage Ledger at epoch completion.
    Rolls up all five pillar records into a single compound-digested entry.

    Schema version: constitutional_evolution_cycle.v1

    CONSTITUTIONAL INVARIANT: EVIDENCE-CHAIN-0
    compound_digest = SHA-256 of canonical JSON of all nested records.
    Any tamper with any field → compound_digest mismatch → ledger integrity failure.

    Ledger write path: data/evolution_ledger.jsonl (append-only JSONL)
    Each line = one serialized EvolutionEvidence record.
    """
    event_type: str                                      # "constitutional_evolution_cycle.v1"
    epoch_evidence: EpochEvidence
    lineage_evidence: tuple[MutationLineageEvidence, ...]
    capability_evidence: tuple[CapabilityVersionEvidence, ...]
    exception_evidence: tuple[GovernanceExceptionEvidence, ...]
    drift_evidence: ModelDriftEvidence
    compound_digest: str                                 # computed on construction — see factory

    @classmethod
    def build(
        cls,
        epoch: EpochEvidence,
        lineages: list[MutationLineageEvidence],
        capabilities: list[CapabilityVersionEvidence],
        exceptions: list[GovernanceExceptionEvidence],
        drift: ModelDriftEvidence,
    ) -> "EvolutionEvidence":
        """
        Factory method: assembles all five pillars and computes compound_digest.
        This is the only sanctioned construction path — do not bypass.
        """
        raw = {
            "event_type": "constitutional_evolution_cycle.v1",
            "epoch_evidence": asdict(epoch),
            "lineage_evidence": [asdict(l) for l in lineages],
            "capability_evidence": [asdict(c) for c in capabilities],
            "exception_evidence": [asdict(e) for e in exceptions],
            "drift_evidence": asdict(drift),
        }
        compound_digest = hashlib.sha256(
            json.dumps(raw, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

        return cls(
            event_type="constitutional_evolution_cycle.v1",
            epoch_evidence=epoch,
            lineage_evidence=tuple(lineages),
            capability_evidence=tuple(capabilities),
            exception_evidence=tuple(exceptions),
            drift_evidence=drift,
            compound_digest=compound_digest,
        )

    def to_ledger_line(self) -> str:
        """Serializes to a single JSONL line for append-only ledger write."""
        return json.dumps(asdict(self), sort_keys=True, default=str)

    def verify_integrity(self) -> bool:
        """
        Re-derives compound_digest from nested records and compares.
        Returns True if record is untampered.
        Used by Aponi EpochEvidence Audit panel and replay_verifier.py.
        """
        raw = {
            "event_type": self.event_type,
            "epoch_evidence": asdict(self.epoch_evidence),
            "lineage_evidence": [asdict(l) for l in self.lineage_evidence],
            "capability_evidence": [asdict(c) for c in self.capability_evidence],
            "exception_evidence": [asdict(e) for e in self.exception_evidence],
            "drift_evidence": asdict(self.drift_evidence),
        }
        expected = hashlib.sha256(
            json.dumps(raw, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return expected == self.compound_digest
