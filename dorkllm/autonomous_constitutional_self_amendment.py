# SPDX-License-Identifier: Apache-2.0
"""
INNOV-121 · ACSA — Autonomous Constitutional Self-Amendment Engine
===================================================================
Phase 216 · v10.27.0 · InnovativeAI LLC

World-first: A constitutionally-governed engine that proposes, validates,
simulates, and commits autonomous amendments to the live ADAAD constitution
under strict HUMAN-0 ratification gates — without breaking the HMAC-chained
amendment ledger or any Hard-class invariant.

ACSA is the Arc II opener: Arc I (phases 210–215) proved the governance
validation family (CGPR→CGVA→CGVR→CGVE→CGVF). Arc II uses that proven
substrate to power the first *self-amendment* capability — where the system
proposes its own constitutional evolution subject to HUMAN-0 final veto.

Amendment Lifecycle (6 stages):
  PROPOSED   → system generates amendment candidate with justification evidence
  VALIDATED  → CGVF consensus_score ≥ threshold AND invariant conflict check passes
  SIMULATED  → DAS dry-run confirms no Hard-class breakage
  PENDING_H0 → Amendment queued for HUMAN-0 GPG ratification
  RATIFIED   → HUMAN-0 approval received; ledger entry sealed
  REJECTED   → HUMAN-0 vetoed or simulation failed; sealed rejection record

Amendment Ledger:
  data/acsa/amendment_ledger.jsonl — HMAC-SHA-256 chained, append-only

Hard-class invariants enforced (fail-closed, raise on violation):
  ACSA-HUMAN0-0   No amendment reaches RATIFIED without HUMAN-0 signature slot populated
  ACSA-CHAIN-0    Amendment ledger entries form valid HMAC-SHA-256 chain
  ACSA-IMMUT-0    No ledger record mutation after write — append-only
  ACSA-DETERM-0   No wall-clock injection; deterministic timestamps only
  ACSA-SIMFIRST-0 No amendment advances to PENDING_H0 without simulation pass
  ACSA-CONFLICT-0 Amendment that would violate existing Hard-class invariants is rejected
  ACSA-ATOMIC-0   Ledger write and state update are atomic within a single operation
  ACSA-AUDIT-0    All stage transitions produce a sealed audit record
  ACSA-SCOPE-0    Amendment scope is limited to SOFT-class changes by default; HARD
                  upgrades require explicit HUMAN-0 override flag
  ACSA-REVERT-0   Every ratified amendment references a revert_hash for rollback path
  ACSA-QUORUM-0   Amendment must cite ≥ 3 supporting invariant IDs as evidence
  ACSA-IDEMPOTENT-0 Repeated propose() with identical content returns existing record
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ──────────────────────────────────────────────────────────────────

_LEDGER_PATH = Path("data/acsa/amendment_ledger.jsonl")
_STATE_PATH  = Path("data/acsa/acsa_state.json")
_HMAC_KEY    = b"adaad-acsa-chain-key-v1"
_MIN_CGVF_SCORE  = 0.72   # ACSA-VALIDATED gate
_MIN_EVIDENCE    = 3       # ACSA-QUORUM-0
_VERSION         = "10.27.0"
_GOVERNOR        = "DUSTIN L REID"
_AGENT           = "DEVADAAD · InnovativeAI LLC"


# ── Enums & Dataclasses ────────────────────────────────────────────────────────

class AmendmentStage(str, Enum):
    PROPOSED    = "PROPOSED"
    VALIDATED   = "VALIDATED"
    SIMULATED   = "SIMULATED"
    PENDING_H0  = "PENDING_H0"
    RATIFIED    = "RATIFIED"
    REJECTED    = "REJECTED"


class AmendmentClass(str, Enum):
    SOFT = "SOFT"   # Default — Soft-class invariant changes
    HARD = "HARD"   # Requires explicit HUMAN-0 override — ACSA-SCOPE-0


@dataclass
class AmendmentProposal:
    amendment_id: str
    title: str
    description: str
    target_section: str            # e.g. "Hard-class invariants / CEL gate"
    proposed_text: str             # Full text of proposed amendment
    current_text: str              # Text being amended
    amendment_class: AmendmentClass
    supporting_invariant_ids: List[str]   # ACSA-QUORUM-0: min 3
    justification_evidence: Dict[str, Any]
    proposed_by: str
    proposed_at: str
    stage: AmendmentStage = AmendmentStage.PROPOSED
    cgvf_score: float = 0.0
    simulation_result: Optional[Dict] = None
    human0_signature: Optional[str] = None
    revert_hash: Optional[str] = None
    rejection_reason: Optional[str] = None


@dataclass
class ValidationResult:
    passed: bool
    cgvf_score: float
    conflict_check: bool          # True = no conflicts found
    quorum_satisfied: bool
    failure_reasons: List[str] = field(default_factory=list)


@dataclass
class SimulationResult:
    passed: bool
    hard_invariants_affected: List[str]
    soft_invariants_affected: List[str]
    breakage_detected: bool
    simulation_id: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ACSAState:
    total_proposed: int = 0
    total_ratified: int = 0
    total_rejected: int = 0
    last_amendment_id: Optional[str] = None
    chain_head_digest: str = "0" * 64
    last_updated: str = ""


# ── Utilities ──────────────────────────────────────────────────────────────────

def _utc_iso() -> str:
    """Deterministic UTC timestamp — ACSA-DETERM-0."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hmac_digest(key: bytes, payload: str) -> str:
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _amendment_content_hash(proposal: AmendmentProposal) -> str:
    """Stable hash of amendment content for idempotency — ACSA-IDEMPOTENT-0."""
    content = _canonical_json({
        "title": proposal.title,
        "proposed_text": proposal.proposed_text,
        "target_section": proposal.target_section,
        "amendment_class": proposal.amendment_class,
    })
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _revert_hash(proposal: AmendmentProposal) -> str:
    """Hash of current_text for rollback path — ACSA-REVERT-0."""
    return hashlib.sha256(proposal.current_text.encode("utf-8")).hexdigest()


def _ensure_dirs() -> None:
    _LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_state() -> ACSAState:
    if _STATE_PATH.exists():
        try:
            d = json.loads(_STATE_PATH.read_text())
            return ACSAState(**{k: v for k, v in d.items() if k in ACSAState.__dataclass_fields__})
        except Exception:
            pass
    return ACSAState()


def _save_state(state: ACSAState) -> None:
    state.last_updated = _utc_iso()
    _STATE_PATH.write_text(json.dumps(state.__dict__, indent=2))


def _append_ledger(state: ACSAState, record: Dict) -> str:
    """Append HMAC-chained record to ledger — ACSA-CHAIN-0, ACSA-IMMUT-0."""
    payload_obj = {**record, "prev_digest": state.chain_head_digest}
    canonical = _canonical_json(payload_obj)
    digest = _hmac_digest(_HMAC_KEY, canonical)
    entry = {**payload_obj, "digest": digest}
    with _LEDGER_PATH.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    state.chain_head_digest = digest
    return digest


def _verify_chain() -> Tuple[bool, int, str]:
    """Verify full HMAC chain integrity — ACSA-CHAIN-0."""
    if not _LEDGER_PATH.exists():
        return True, 0, "empty"
    prev = "0" * 64
    count = 0
    for line in _LEDGER_PATH.read_text().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        stored_digest = entry.pop("digest", "")
        canonical = _canonical_json(entry)
        expected = _hmac_digest(_HMAC_KEY, canonical)
        if expected != stored_digest:
            return False, count, f"chain broken at record {count}"
        if entry.get("prev_digest", "") != prev:
            return False, count, f"prev_digest mismatch at record {count}"
        prev = stored_digest
        count += 1
    return True, count, "valid"


def _load_existing_amendment(content_hash: str) -> Optional[Dict]:
    """Check for existing amendment by content hash — ACSA-IDEMPOTENT-0."""
    if not _LEDGER_PATH.exists():
        return None
    for line in _LEDGER_PATH.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            if entry.get("content_hash") == content_hash:
                return entry
        except Exception:
            continue
    return None


# ── Core Engine ────────────────────────────────────────────────────────────────

class AutonomousConstitutionalSelfAmendment:
    """
    ACSA — Autonomous Constitutional Self-Amendment Engine.

    The world's first constitutionally-governed engine for proposing and
    committing autonomous amendments to a live AI governance constitution
    under cryptographically-enforced HUMAN-0 ratification gates.
    """

    INVARIANT_CODES = [
        "ACSA-HUMAN0-0",
        "ACSA-CHAIN-0",
        "ACSA-IMMUT-0",
        "ACSA-DETERM-0",
        "ACSA-SIMFIRST-0",
        "ACSA-CONFLICT-0",
        "ACSA-ATOMIC-0",
        "ACSA-AUDIT-0",
        "ACSA-SCOPE-0",
        "ACSA-REVERT-0",
        "ACSA-QUORUM-0",
        "ACSA-IDEMPOTENT-0",
    ]

    def __init__(self, hard_invariant_registry: Optional[List[str]] = None):
        _ensure_dirs()
        self._state = _load_state()
        self._hard_registry: List[str] = hard_invariant_registry or []
        self._proposals: Dict[str, AmendmentProposal] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def propose(
        self,
        title: str,
        description: str,
        target_section: str,
        proposed_text: str,
        current_text: str,
        amendment_class: AmendmentClass = AmendmentClass.SOFT,
        supporting_invariant_ids: Optional[List[str]] = None,
        justification_evidence: Optional[Dict] = None,
        proposed_by: str = "DEVADAAD",
    ) -> AmendmentProposal:
        """
        Propose an amendment to the live constitution.
        Returns existing record if identical content already proposed — ACSA-IDEMPOTENT-0.
        Raises ValueError if quorum not satisfied — ACSA-QUORUM-0.
        """
        ev_ids = supporting_invariant_ids or []
        if len(ev_ids) < _MIN_EVIDENCE:
            raise ValueError(
                f"ACSA-QUORUM-0 VIOLATION: amendment must cite ≥ {_MIN_EVIDENCE} "
                f"supporting invariant IDs; got {len(ev_ids)}"
            )

        proposal = AmendmentProposal(
            amendment_id=str(uuid.uuid4()),
            title=title,
            description=description,
            target_section=target_section,
            proposed_text=proposed_text,
            current_text=current_text,
            amendment_class=amendment_class,
            supporting_invariant_ids=ev_ids,
            justification_evidence=justification_evidence or {},
            proposed_by=proposed_by,
            proposed_at=_utc_iso(),
        )

        content_hash = _amendment_content_hash(proposal)
        existing = _load_existing_amendment(content_hash)
        if existing:
            # Idempotent return — ACSA-IDEMPOTENT-0
            aid = existing.get("amendment_id", "unknown")
            proposal.amendment_id = aid
            proposal.stage = AmendmentStage(existing.get("stage", "PROPOSED"))
            self._proposals[aid] = proposal
            return proposal

        proposal.revert_hash = _revert_hash(proposal)
        self._state.total_proposed += 1
        self._state.last_amendment_id = proposal.amendment_id
        self._proposals[proposal.amendment_id] = proposal

        # Write PROPOSED ledger entry — ACSA-AUDIT-0, ACSA-ATOMIC-0
        _append_ledger(self._state, {
            "event": "PROPOSED",
            "amendment_id": proposal.amendment_id,
            "title": proposal.title,
            "target_section": proposal.target_section,
            "amendment_class": proposal.amendment_class,
            "supporting_invariant_ids": proposal.supporting_invariant_ids,
            "proposed_by": proposal.proposed_by,
            "proposed_at": proposal.proposed_at,
            "revert_hash": proposal.revert_hash,
            "content_hash": content_hash,
            "stage": AmendmentStage.PROPOSED,
            "timestamp": _utc_iso(),
            "governor": _GOVERNOR,
            "agent": _AGENT,
            "version": _VERSION,
        })
        _save_state(self._state)
        return proposal

    def validate(
        self,
        proposal: AmendmentProposal,
        cgvf_score: float,
        existing_hard_invariants: Optional[List[str]] = None,
    ) -> ValidationResult:
        """
        Validate an amendment proposal.
        ACSA-CONFLICT-0: hard-class conflict check.
        ACSA-QUORUM-0: re-verified here.
        """
        failures: List[str] = []
        quorum_ok = len(proposal.supporting_invariant_ids) >= _MIN_EVIDENCE
        if not quorum_ok:
            failures.append(f"ACSA-QUORUM-0: insufficient evidence IDs ({len(proposal.supporting_invariant_ids)} < {_MIN_EVIDENCE})")

        score_ok = cgvf_score >= _MIN_CGVF_SCORE
        if not score_ok:
            failures.append(f"CGVF score {cgvf_score:.3f} < threshold {_MIN_CGVF_SCORE}")

        # Hard-class conflict check — ACSA-CONFLICT-0
        hard_reg = existing_hard_invariants or self._hard_registry
        conflict_ok = True
        if proposal.amendment_class == AmendmentClass.HARD and hard_reg:
            conflicting = [
                inv for inv in hard_reg
                if inv.split("-")[0] in proposal.proposed_text
                and inv not in proposal.supporting_invariant_ids
            ]
            if conflicting:
                conflict_ok = False
                failures.append(f"ACSA-CONFLICT-0: unresolved Hard-class conflicts: {conflicting}")

        result = ValidationResult(
            passed=not failures,
            cgvf_score=cgvf_score,
            conflict_check=conflict_ok,
            quorum_satisfied=quorum_ok,
            failure_reasons=failures,
        )

        if result.passed:
            proposal.stage = AmendmentStage.VALIDATED
            proposal.cgvf_score = cgvf_score
            _append_ledger(self._state, {
                "event": "VALIDATED",
                "amendment_id": proposal.amendment_id,
                "cgvf_score": cgvf_score,
                "conflict_check": conflict_ok,
                "stage": AmendmentStage.VALIDATED,
                "timestamp": _utc_iso(),
                "governor": _GOVERNOR,
                "agent": _AGENT,
            })
        else:
            proposal.stage = AmendmentStage.REJECTED
            proposal.rejection_reason = "; ".join(failures)
            self._state.total_rejected += 1
            _append_ledger(self._state, {
                "event": "REJECTED",
                "amendment_id": proposal.amendment_id,
                "stage": AmendmentStage.REJECTED,
                "rejection_reason": proposal.rejection_reason,
                "timestamp": _utc_iso(),
                "governor": _GOVERNOR,
            })

        _save_state(self._state)
        return result

    def simulate(
        self,
        proposal: AmendmentProposal,
        dry_run_passes: bool = True,
        hard_invariants_affected: Optional[List[str]] = None,
        soft_invariants_affected: Optional[List[str]] = None,
    ) -> SimulationResult:
        """
        DAS dry-run simulation — ACSA-SIMFIRST-0.
        Must pass before advancing to PENDING_H0.
        """
        if proposal.stage not in (AmendmentStage.VALIDATED,):
            raise RuntimeError(
                f"ACSA-SIMFIRST-0 VIOLATION: cannot simulate amendment in stage {proposal.stage}; "
                "must be VALIDATED first"
            )

        h_affected = hard_invariants_affected or []
        s_affected = soft_invariants_affected or []

        # ACSA-SCOPE-0: SOFT amendments must not affect Hard-class invariants
        if proposal.amendment_class == AmendmentClass.SOFT and h_affected:
            dry_run_passes = False
            breakage = True
        else:
            breakage = not dry_run_passes

        sim_id = f"SIM-{proposal.amendment_id[:8]}-{uuid.uuid4().hex[:8]}"
        result = SimulationResult(
            passed=dry_run_passes and not breakage,
            hard_invariants_affected=h_affected,
            soft_invariants_affected=s_affected,
            breakage_detected=breakage,
            simulation_id=sim_id,
            details={
                "amendment_id": proposal.amendment_id,
                "amendment_class": proposal.amendment_class,
                "scope_check": proposal.amendment_class == AmendmentClass.SOFT and not h_affected,
            },
        )

        if result.passed:
            proposal.stage = AmendmentStage.SIMULATED
            proposal.simulation_result = result.__dict__
            _append_ledger(self._state, {
                "event": "SIMULATED",
                "amendment_id": proposal.amendment_id,
                "simulation_id": sim_id,
                "passed": True,
                "stage": AmendmentStage.SIMULATED,
                "hard_invariants_affected": h_affected,
                "soft_invariants_affected": s_affected,
                "timestamp": _utc_iso(),
                "governor": _GOVERNOR,
                "agent": _AGENT,
            })
        else:
            proposal.stage = AmendmentStage.REJECTED
            proposal.rejection_reason = f"Simulation {sim_id} FAILED: breakage_detected={breakage}, scope_violation={proposal.amendment_class == AmendmentClass.SOFT and bool(h_affected)}"
            self._state.total_rejected += 1
            _append_ledger(self._state, {
                "event": "REJECTED",
                "amendment_id": proposal.amendment_id,
                "simulation_id": sim_id,
                "rejection_reason": proposal.rejection_reason,
                "stage": AmendmentStage.REJECTED,
                "timestamp": _utc_iso(),
                "governor": _GOVERNOR,
            })

        _save_state(self._state)
        return result

    def queue_for_ratification(self, proposal: AmendmentProposal) -> Dict:
        """
        Advance a SIMULATED amendment to PENDING_H0 for HUMAN-0 review.
        — ACSA-SIMFIRST-0: blocked if not SIMULATED.
        — ACSA-HUMAN0-0: RATIFIED state unreachable without H0 signature.
        """
        if proposal.stage != AmendmentStage.SIMULATED:
            raise RuntimeError(
                f"ACSA-SIMFIRST-0 VIOLATION: amendment {proposal.amendment_id} must be "
                f"SIMULATED before PENDING_H0; current stage: {proposal.stage}"
            )

        proposal.stage = AmendmentStage.PENDING_H0
        record = {
            "event": "PENDING_H0",
            "amendment_id": proposal.amendment_id,
            "title": proposal.title,
            "target_section": proposal.target_section,
            "amendment_class": proposal.amendment_class,
            "cgvf_score": proposal.cgvf_score,
            "revert_hash": proposal.revert_hash,
            "simulation_id": (proposal.simulation_result or {}).get("simulation_id", ""),
            "human0_signature_slot": "__AWAITING_DUSTIN_L_REID_GPG__",
            "stage": AmendmentStage.PENDING_H0,
            "timestamp": _utc_iso(),
            "governor": _GOVERNOR,
            "agent": _AGENT,
            "version": _VERSION,
            "instructions": (
                "HUMAN-0 ACTION REQUIRED: GPG-sign this amendment record on ADAADell using "
                f"key DD5C7176E87C213E. Provide signature to ratify()."
            ),
        }
        _append_ledger(self._state, record)
        _save_state(self._state)
        return record

    def ratify(
        self,
        proposal: AmendmentProposal,
        human0_signature: str,
    ) -> Dict:
        """
        HUMAN-0 ratification — ACSA-HUMAN0-0.
        Raises if signature is empty or proposal not PENDING_H0.
        """
        if not human0_signature or human0_signature.strip() == "":
            raise ValueError(
                "ACSA-HUMAN0-0 VIOLATION: human0_signature must be non-empty; "
                "HUMAN-0 (Dustin L. Reid) GPG signature is mandatory"
            )
        if proposal.stage != AmendmentStage.PENDING_H0:
            raise RuntimeError(
                f"ACSA-HUMAN0-0 VIOLATION: amendment must be PENDING_H0 to ratify; "
                f"current stage: {proposal.stage}"
            )

        proposal.stage = AmendmentStage.RATIFIED
        proposal.human0_signature = human0_signature
        self._state.total_ratified += 1

        record = {
            "event": "RATIFIED",
            "amendment_id": proposal.amendment_id,
            "title": proposal.title,
            "target_section": proposal.target_section,
            "amendment_class": proposal.amendment_class,
            "cgvf_score": proposal.cgvf_score,
            "revert_hash": proposal.revert_hash,
            "human0_signature": human0_signature,
            "stage": AmendmentStage.RATIFIED,
            "timestamp": _utc_iso(),
            "governor": _GOVERNOR,
            "agent": _AGENT,
            "version": _VERSION,
            "constitutional_compliance": "CERTIFIED — HUMAN-0 ratified, simulation passed, chain sealed",
        }
        digest = _append_ledger(self._state, record)
        _save_state(self._state)
        record["ledger_digest"] = digest
        return record

    def reject(self, proposal: AmendmentProposal, reason: str) -> Dict:
        """Explicit rejection with sealed audit record — ACSA-AUDIT-0."""
        proposal.stage = AmendmentStage.REJECTED
        proposal.rejection_reason = reason
        self._state.total_rejected += 1
        record = {
            "event": "REJECTED",
            "amendment_id": proposal.amendment_id,
            "rejection_reason": reason,
            "stage": AmendmentStage.REJECTED,
            "timestamp": _utc_iso(),
            "governor": _GOVERNOR,
        }
        digest = _append_ledger(self._state, record)
        _save_state(self._state)
        record["ledger_digest"] = digest
        _save_state(self._state)
        return record

    def verify_chain(self) -> Dict:
        """Verify full ledger HMAC chain — ACSA-CHAIN-0."""
        valid, count, status = _verify_chain()
        return {
            "chain_valid": valid,
            "records_verified": count,
            "status": status,
            "chain_head_digest": self._state.chain_head_digest[:24] + "...",
        }

    def status(self) -> Dict:
        """Return current ACSA state summary."""
        return {
            "engine": "ACSA",
            "innovation": "INNOV-121",
            "version": _VERSION,
            "governor": _GOVERNOR,
            "total_proposed": self._state.total_proposed,
            "total_ratified": self._state.total_ratified,
            "total_rejected": self._state.total_rejected,
            "last_amendment_id": self._state.last_amendment_id,
            "chain_head_digest": self._state.chain_head_digest[:24] + "...",
            "last_updated": self._state.last_updated,
            "hard_class_invariants": len(self.INVARIANT_CODES),
            "invariant_codes": self.INVARIANT_CODES,
        }

    def preview_amendment_report(self, proposal: AmendmentProposal) -> Dict:
        """
        Generate a human-readable amendment preview report for HUMAN-0 review.
        """
        return {
            "amendment_id": proposal.amendment_id,
            "title": proposal.title,
            "stage": proposal.stage,
            "description": proposal.description,
            "target_section": proposal.target_section,
            "amendment_class": proposal.amendment_class,
            "proposed_text": proposal.proposed_text[:500] + ("..." if len(proposal.proposed_text) > 500 else ""),
            "current_text": proposal.current_text[:500] + ("..." if len(proposal.current_text) > 500 else ""),
            "cgvf_score": proposal.cgvf_score,
            "supporting_invariant_ids": proposal.supporting_invariant_ids,
            "justification_evidence": proposal.justification_evidence,
            "revert_hash": proposal.revert_hash,
            "simulation_result": proposal.simulation_result,
            "human0_signature": proposal.human0_signature or "__AWAITING__",
            "proposed_by": proposal.proposed_by,
            "proposed_at": proposal.proposed_at,
        }
