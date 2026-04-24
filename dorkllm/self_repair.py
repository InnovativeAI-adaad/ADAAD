# SPDX-License-Identifier: Apache-2.0
"""Phase 158 — INNOV-64 · CSR — Constitutional Self-Repair Engine

Reads the live GHI score, identifies sub-index degradation, generates targeted
repair proposals, and records each proposal into the CGTH telemetry ledger.

The CSR closes the full governance feedback loop:
  detect (CGAI) → score (GHI) → propose repair (CSR) → record (CGTH)

CSR never applies mutations autonomously.  It is a proposal-only engine:
every repair action is a recommendation to HUMAN-0 or the governed mutation
pipeline.  This preserves the ADAAD constitutional principle:
"ADAAD proposes — humans decide."

Score-band thresholds
======================
NOMINAL   (≥ 0.90)  No action required.
CAUTION   (≥ 0.75)  Low-priority proposals generated for degraded sub-indices.
ELEVATED  (≥ 0.50)  Standard-priority proposals generated; advisory issued.
CRITICAL  (< 0.50)  Urgent proposals generated; HUMAN-0 alert emitted to CGTH.

Constitutional Invariants
==========================
CSR-PROPOSE-0   : CSR only generates repair *proposals*.  It MUST NOT apply
                  any mutation, file change, or configuration override without
                  a HUMAN-0 authorisation record in CGTH.
CSR-DETERM-0    : Given identical (ghi_snapshot, anomaly_findings), generate()
                  always produces the same proposal_id (SHA-256 of canonical
                  payload).  No wall-clock time enters the hash.
CSR-EMIT-0      : Every call to generate() that produces ≥1 proposal MUST
                  emit a CSR_PROPOSAL event to CGTH before returning.
CSR-CRITICAL-0  : When band == CRITICAL, generate() MUST also emit a
                  CSR_HUMAN0_ALERT event to CGTH regardless of proposal count.
CSR-BOUNDED-0   : A single generate() call MUST NOT produce more than
                  MAX_PROPOSALS_PER_RUN proposals (default 10) to prevent
                  proposal floods.

Patent note (InnovativeAI LLC): A closed-loop Constitutional Self-Repair
architecture that derives targeted repair proposals from a composite health
index and re-emits them into a cryptographically chained governance telemetry
ledger constitutes a novel Autonomous Constitutional Self-Repair primitive for
governed AI systems — filed as IP under InnovativeAI LLC.

Author: DEVADAAD · InnovativeAI LLC
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from dorkllm.governance_health import HealthSnapshot, HealthBand, get_ghi, score_now
from dorkllm.telemetry_hub import (
    CGTHEventType,
    ConstitutionalGovernanceTelemetryHub,
    get_hub,
)

# ---------------------------------------------------------------------------
# New event types contributed by CSR to CGTH taxonomy
# (CSR uses the existing CGTH infrastructure; these are logical labels embedded
#  in the payload rather than new enum values, keeping CGTH-CHAIN-0 stable.)
# ---------------------------------------------------------------------------

_CSR_PROPOSAL_EVENT   = "CSR_PROPOSAL"
_CSR_ALERT_EVENT      = "CSR_HUMAN0_ALERT"

MAX_PROPOSALS_PER_RUN: int = 10

# Sub-index names (mirror GHI internal labels)
_SUBINDEX_NAMES = ("pressure", "throttle", "anomaly", "gate", "stability")


# ---------------------------------------------------------------------------
# Repair action taxonomy
# ---------------------------------------------------------------------------

class RepairAction(str, Enum):
    REDUCE_MUTATION_RATE      = "REDUCE_MUTATION_RATE"
    INCREASE_THROTTLE_FLOOR   = "INCREASE_THROTTLE_FLOOR"
    FLUSH_ANOMALY_BACKLOG     = "FLUSH_ANOMALY_BACKLOG"
    AUDIT_GATE_CONFIGURATION  = "AUDIT_GATE_CONFIGURATION"
    REVIEW_CIRCUIT_BREAKER    = "REVIEW_CIRCUIT_BREAKER"
    INCREASE_COOLDOWN_PERIOD  = "INCREASE_COOLDOWN_PERIOD"
    ESCALATE_TO_HUMAN0        = "ESCALATE_TO_HUMAN0"
    RERUN_REPLAY_VERIFICATION = "RERUN_REPLAY_VERIFICATION"
    CLEAR_PRESSURE_DOMAINS    = "CLEAR_PRESSURE_DOMAINS"
    NO_ACTION                 = "NO_ACTION"


class RepairPriority(str, Enum):
    LOW      = "LOW"
    STANDARD = "STANDARD"
    URGENT   = "URGENT"


# ---------------------------------------------------------------------------
# Proposal dataclass
# ---------------------------------------------------------------------------

@dataclass
class RepairProposal:
    """A single CSR repair proposal.

    CSR-PROPOSE-0: proposals are advisory only; no autonomous mutation.
    CSR-DETERM-0:  proposal_id is deterministic from (action, target, rationale).
    """
    action:     RepairAction
    target:     str            # sub-index or subsystem this proposal addresses
    rationale:  str            # human-readable explanation
    priority:   RepairPriority
    evidence:   Dict[str, Any] = field(default_factory=dict)

    # Computed on post-init
    proposal_id: str = field(init=False)

    def __post_init__(self) -> None:
        raw = json.dumps(
            {"action": self.action.value, "target": self.target, "rationale": self.rationale},
            sort_keys=True, separators=(",", ":")
        )
        self.proposal_id = hashlib.sha256(raw.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "action":      self.action.value,
            "target":      self.target,
            "rationale":   self.rationale,
            "priority":    self.priority.value,
            "evidence":    self.evidence,
        }


# ---------------------------------------------------------------------------
# Proposal generator functions (one per sub-index / scenario)
# ---------------------------------------------------------------------------

def _proposals_for_pressure(score: float, band: HealthBand) -> List[RepairProposal]:
    """Generate repair proposals for a degraded pressure sub-index."""
    if score >= 0.90:
        return []
    priority = RepairPriority.URGENT if band == HealthBand.CRITICAL else RepairPriority.STANDARD
    return [
        RepairProposal(
            action    = RepairAction.REDUCE_MUTATION_RATE,
            target    = "pressure",
            rationale = f"Constitutional pressure sub-index at {score:.3f}; mutation rate reduction advised.",
            priority  = priority,
            evidence  = {"pressure_score": score},
        ),
        RepairProposal(
            action    = RepairAction.CLEAR_PRESSURE_DOMAINS,
            target    = "pressure",
            rationale = "Audit active pressure domains and clear saturated MUTATION/STABILITY buckets.",
            priority  = RepairPriority.LOW if score >= 0.5 else RepairPriority.STANDARD,
            evidence  = {"pressure_score": score},
        ),
    ]


def _proposals_for_throttle(score: float, band: HealthBand) -> List[RepairProposal]:
    """Generate repair proposals for a degraded throttle sub-index."""
    if score >= 0.90:
        return []
    priority = RepairPriority.URGENT if band == HealthBand.CRITICAL else RepairPriority.STANDARD
    return [
        RepairProposal(
            action    = RepairAction.INCREASE_THROTTLE_FLOOR,
            target    = "throttle",
            rationale = f"Adaptive throttle sub-index at {score:.3f}; raise throttle floor to reduce mutation pressure.",
            priority  = priority,
            evidence  = {"throttle_score": score},
        ),
        RepairProposal(
            action    = RepairAction.INCREASE_COOLDOWN_PERIOD,
            target    = "throttle",
            rationale = "Extend inter-mutation cooldown to allow subsystem stabilisation.",
            priority  = RepairPriority.LOW,
            evidence  = {"throttle_score": score},
        ),
    ]


def _proposals_for_anomaly(score: float, band: HealthBand) -> List[RepairProposal]:
    """Generate repair proposals for a degraded anomaly sub-index."""
    if score >= 0.90:
        return []
    priority = RepairPriority.URGENT if band == HealthBand.CRITICAL else RepairPriority.STANDARD
    return [
        RepairProposal(
            action    = RepairAction.FLUSH_ANOMALY_BACKLOG,
            target    = "anomaly",
            rationale = f"CGAI anomaly sub-index at {score:.3f}; review and remediate open findings.",
            priority  = priority,
            evidence  = {"anomaly_score": score},
        ),
    ]


def _proposals_for_gate(score: float, band: HealthBand) -> List[RepairProposal]:
    """Generate repair proposals for a degraded gate pass-rate sub-index."""
    if score >= 0.90:
        return []
    priority = RepairPriority.URGENT if band == HealthBand.CRITICAL else RepairPriority.STANDARD
    return [
        RepairProposal(
            action    = RepairAction.AUDIT_GATE_CONFIGURATION,
            target    = "gate",
            rationale = f"Gate pass-rate sub-index at {score:.3f}; audit CPAG and GovernanceGate configuration.",
            priority  = priority,
            evidence  = {"gate_score": score},
        ),
    ]


def _proposals_for_stability(score: float, band: HealthBand) -> List[RepairProposal]:
    """Generate repair proposals for a degraded stability sub-index."""
    if score >= 0.90:
        return []
    priority = RepairPriority.URGENT if band == HealthBand.CRITICAL else RepairPriority.STANDARD
    return [
        RepairProposal(
            action    = RepairAction.REVIEW_CIRCUIT_BREAKER,
            target    = "stability",
            rationale = f"Stability sub-index at {score:.3f}; review circuit breaker trip history and rollback rate.",
            priority  = priority,
            evidence  = {"stability_score": score},
        ),
        RepairProposal(
            action    = RepairAction.RERUN_REPLAY_VERIFICATION,
            target    = "stability",
            rationale = "Rerun deterministic replay verification to rule out governance drift.",
            priority  = RepairPriority.LOW,
            evidence  = {"stability_score": score},
        ),
    ]


_SUBINDEX_GENERATORS = {
    "pressure":  _proposals_for_pressure,
    "throttle":  _proposals_for_throttle,
    "anomaly":   _proposals_for_anomaly,
    "gate":      _proposals_for_gate,
    "stability": _proposals_for_stability,
}


# ---------------------------------------------------------------------------
# CSR result container
# ---------------------------------------------------------------------------

@dataclass
class RepairRun:
    """Result of a single CSR generate() invocation."""
    band:      HealthBand
    ghi_score: float
    proposals: List[RepairProposal]
    alert_emitted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "band":          self.band.value,
            "ghi_score":     self.ghi_score,
            "proposal_count": len(self.proposals),
            "alert_emitted":  self.alert_emitted,
            "proposals":     [p.to_dict() for p in self.proposals],
        }


# ---------------------------------------------------------------------------
# CSR engine
# ---------------------------------------------------------------------------

class ConstitutionalSelfRepairEngine:
    """CSR — Constitutional Self-Repair Engine.

    Usage::

        csr = ConstitutionalSelfRepairEngine()
        run = csr.generate()          # uses live GHI score
        run = csr.generate(snapshot)  # uses a pre-computed snapshot

    CSR-PROPOSE-0: only produces proposals — never applies mutations.
    """

    def __init__(
        self,
        hub: Optional[ConstitutionalGovernanceTelemetryHub] = None,
        max_proposals: int = MAX_PROPOSALS_PER_RUN,
    ) -> None:
        self._hub = hub or get_hub()
        self._max = max_proposals

    # ------------------------------------------------------------------
    # Main entrypoint
    # ------------------------------------------------------------------

    def generate(
        self,
        snapshot: Optional[HealthSnapshot] = None,
    ) -> RepairRun:
        """Generate repair proposals from the current (or supplied) GHI snapshot.

        CSR-EMIT-0    : emits CSR_PROPOSAL to CGTH if any proposals generated.
        CSR-CRITICAL-0: emits CSR_HUMAN0_ALERT to CGTH when band == CRITICAL.
        CSR-BOUNDED-0 : caps total proposals at self._max.
        """
        snap = snapshot if snapshot is not None else score_now()

        band      = snap.band
        ghi_score = snap.score
        sub       = snap.sub_scores          # Dict[str, float]

        # No action for NOMINAL health (fast path)
        if band == HealthBand.NOMINAL:
            return RepairRun(band=band, ghi_score=ghi_score, proposals=[])

        # Build proposals from each degraded sub-index
        proposals: List[RepairProposal] = []
        for name, gen_fn in _SUBINDEX_GENERATORS.items():
            sub_score = sub.get(name, 1.0)
            new_props = gen_fn(sub_score, band)
            proposals.extend(new_props)
            if len(proposals) >= self._max:
                proposals = proposals[: self._max]
                break

        # For CRITICAL band, always add an escalation proposal (CSR-CRITICAL-0)
        if band == HealthBand.CRITICAL and len(proposals) < self._max:
            proposals.insert(
                0,
                RepairProposal(
                    action    = RepairAction.ESCALATE_TO_HUMAN0,
                    target    = "system",
                    rationale = f"GHI CRITICAL ({ghi_score:.3f}) — immediate HUMAN-0 review required.",
                    priority  = RepairPriority.URGENT,
                    evidence  = {"band": band.value, "ghi_score": ghi_score},
                ),
            )

        alert_emitted = False

        # CSR-EMIT-0: emit proposal event if any proposals exist
        if proposals:
            self._hub.emit_event(
                component_id = "csr",
                event_type   = CGTHEventType.MUTATION_PROPOSED,
                payload      = {
                    "event_label":    _CSR_PROPOSAL_EVENT,
                    "band":           band.value,
                    "ghi_score":      ghi_score,
                    "proposal_count": len(proposals),
                    "proposals":      [p.to_dict() for p in proposals],
                },
            )

        # CSR-CRITICAL-0: emit HUMAN0_ALERT when band is CRITICAL
        if band == HealthBand.CRITICAL:
            self._hub.emit_event(
                component_id = "csr",
                event_type   = CGTHEventType.HUMAN0_AUTHORISATION,
                payload      = {
                    "event_label": _CSR_ALERT_EVENT,
                    "authority":   "REQUIRED",
                    "reason":      f"GHI CRITICAL at {ghi_score:.3f}; human review required.",
                    "ghi_score":   ghi_score,
                    "sub_scores":  sub,
                },
            )
            alert_emitted = True

        return RepairRun(
            band          = band,
            ghi_score     = ghi_score,
            proposals     = proposals,
            alert_emitted = alert_emitted,
        )

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def quick_status(self) -> Dict[str, Any]:
        """Return a JSON-serialisable status dict without emitting to CGTH."""
        snap = score_now()
        return {
            "band":      snap.band.value,
            "ghi_score": snap.score,
            "healthy":   snap.band == HealthBand.NOMINAL,
            "advisory":  snap.advisory,
        }


# ---------------------------------------------------------------------------
# Module-level singleton + convenience
# ---------------------------------------------------------------------------

_default_csr: Optional[ConstitutionalSelfRepairEngine] = None


def get_csr() -> ConstitutionalSelfRepairEngine:
    """Return the process-singleton CSR engine."""
    global _default_csr
    if _default_csr is None:
        _default_csr = ConstitutionalSelfRepairEngine()
    return _default_csr


def repair_now(snapshot: Optional[HealthSnapshot] = None) -> RepairRun:
    """Module-level convenience: generate repair proposals from the singleton."""
    return get_csr().generate(snapshot)
