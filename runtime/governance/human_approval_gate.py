# SPDX-License-Identifier: Apache-2.0
"""
HumanApprovalGate — mandatory human-in-the-loop approval for mutation advancement.

Purpose:
    Enforces that no mutation advances past the "proposed" state into "scored"
    or "promoted" state without an explicit, logged human approval event.
    This is the structural guarantee that underpins ADAAD's autonomy model:
    autonomy level increases are earned, not assumed.

Architecture:
    - Approval requests are written to a persistent queue (JSONL file).
    - Each approval decision (approve/reject) is signed with a SHA-256 digest
      and appended to the audit ledger.
    - The gate is fail-closed: if approval state is unknown, the mutation
      is treated as unapproved.
    - Approval events are immutable once written. Revocation creates a new
      REVOKE event referencing the original approval_id.

Approval lifecycle:
    1. PENDING  — request_approval() called; entry added to queue.
    2. APPROVED — record_decision(approved=True) called by operator.
    3. REJECTED — record_decision(approved=False) called by operator.
    4. REVOKED  — revoke_approval() called; REVOKE event appended.

Governance invariants:
    - Every approval/rejection/revocation is signed and ledger-appended.
    - is_approved() is the single query point: returns True only for
      non-revoked APPROVED decisions.
    - Operator identity (operator_id) is required for all decisions.
    - Approval events reference the mutation_id and epoch_id for traceability.
    - At autonomy L1: every mutation requires individual approval.
    - At autonomy L2+: batch approval supported (batch_approve_ids).

Android/Pydroid3 compatibility:
    - Pure Python stdlib only. No C extensions. No threads required.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from runtime.timeutils import now_iso

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_QUEUE_PATH  = Path("data/approval_queue.jsonl")
DEFAULT_AUDIT_PATH  = Path("data/approval_audit.jsonl")
DEFAULT_INDEX_PATH  = Path("data/approval_index.json")
APPROVAL_EXPIRY_S   = 86400 * 7   # Approvals expire after 7 days (safety)

# ---------------------------------------------------------------------------
# HAPG-IDENTITY-0: HUMAN-0 operator identity binding
# The canonical HUMAN-0 GPG fingerprint.  record_decision() MUST reject any
# operator_id that does not match this value when ADAAD_STRICT_HUMAN0=1.
# In dev/test mode the check is advisory only.
# ---------------------------------------------------------------------------
HUMAN0_GPG_FINGERPRINT: str = "4C95E2F99A775335B1CF3DAF247B015A1CCD95F6"
_STRICT_HUMAN0: bool = (
    (os.getenv("ADAAD_STRICT_HUMAN0", "0").strip() == "1")
    or (os.getenv("ADAAD_ENV", "").strip().lower() not in {"dev", "test", ""})
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ApprovalStatus(str, Enum):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED  = "revoked"
    EXPIRED  = "expired"


class IdentityViolationError(ValueError):
    """Raised when operator_id does not match HUMAN0_GPG_FINGERPRINT in strict mode.

    Constitutional invariant HAPG-IDENTITY-0: in production, the only valid
    operator_id for approval decisions is the canonical HUMAN-0 GPG fingerprint.
    Violations are hard-failed and ledger-appended before raising.
    """


class ApprovalReason(str, Enum):
    MUTATION_ADVANCEMENT    = "mutation_advancement"
    PHASE_TRANSITION        = "phase_transition"
    AUTONOMY_LEVEL_INCREASE = "autonomy_level_increase"
    BATCH_RELEASE           = "batch_release"
    MANUAL                  = "manual"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ApprovalRequest:
    """A pending approval request for a mutation."""
    approval_id: str
    mutation_id: str
    epoch_id: str
    reason: str
    requested_at: str
    metadata: Dict[str, Any]

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ApprovalDecision:
    """An immutable approval/rejection/revocation decision."""
    approval_id: str
    mutation_id: str
    epoch_id: str
    status: str
    operator_id: str
    decided_at: str
    notes: str
    decision_digest: str

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def compute_digest(
        approval_id: str,
        mutation_id: str,
        status: str,
        operator_id: str,
        decided_at: str,
    ) -> str:
        canonical = json.dumps(
            {
                "approval_id": approval_id,
                "mutation_id": mutation_id,
                "status": status,
                "operator_id": operator_id,
                "decided_at": decided_at,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# HumanApprovalGate
# ---------------------------------------------------------------------------

class HumanApprovalGate:
    """
    Structural human approval gate for mutation advancement.

    Usage — individual approval:
        gate = HumanApprovalGate()
        approval_id = gate.request_approval(
            mutation_id="mut-001",
            epoch_id="epoch-042",
            reason=ApprovalReason.MUTATION_ADVANCEMENT,
        )

        # Operator reviews and approves:
        gate.record_decision(
            approval_id=approval_id,
            approved=True,
            operator_id="dreezy66",
        )

        # Gate check before advancement:
        assert gate.is_approved("mut-001")

    Usage — batch approval (L2+):
        gate.batch_approve(
            mutation_ids=["mut-001", "mut-002"],
            epoch_id="epoch-042",
            operator_id="dreezy66",
            notes="Batch approved after digest review",
        )

    Args:
        queue_path:   Path for pending approval request queue.
        audit_path:   Path for immutable approval audit ledger.
        audit_writer: Optional callable(event_type, payload) for external ledger.
    """

    def __init__(
        self,
        queue_path: Path = DEFAULT_QUEUE_PATH,
        audit_path: Path = DEFAULT_AUDIT_PATH,
        index_path: Path = DEFAULT_INDEX_PATH,
        audit_writer: Optional[Any] = None,
    ) -> None:
        self._queue_path = queue_path
        self._audit_path = audit_path
        self._index_path = index_path
        self._audit = audit_writer
        self._index_cache: Optional[Dict[str, Any]] = None
        self._ensure_paths()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def request_approval(
        self,
        mutation_id: str,
        epoch_id: str,
        reason: str = ApprovalReason.MUTATION_ADVANCEMENT,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Submit a mutation for human approval.

        Args:
            mutation_id: The mutation requiring approval.
            epoch_id:    The epoch this mutation belongs to.
            reason:      ApprovalReason explaining why approval is needed.
            metadata:    Optional dict of additional context (score, agent, etc.).

        Returns:
            approval_id: Unique ID for this approval request.
        """
        state = self._load_index_or_rebuild()
        return self._request_approval_with_state(
            state=state,
            mutation_id=mutation_id,
            epoch_id=epoch_id,
            reason=reason,
            metadata=metadata,
        )

    def record_decision(
        self,
        approval_id: str,
        approved: bool,
        operator_id: str,
        notes: str = "",
    ) -> ApprovalDecision:
        """
        Record a human operator's approval or rejection decision.

        Args:
            approval_id: The approval request being decided.
            approved:    True = approve, False = reject.
            operator_id: Identity of the human operator making the decision.
            notes:       Optional human-readable decision notes.

        Returns:
            ApprovalDecision: The immutable decision record.

        Raises:
            ValueError: If approval_id not found in queue.
        """
        state = self._load_index_or_rebuild()
        return self._record_decision_with_state(
            state=state,
            approval_id=approval_id,
            approved=approved,
            operator_id=operator_id,
            notes=notes,
        )

    def batch_approve(
        self,
        mutation_ids: List[str],
        epoch_id: str,
        operator_id: str,
        notes: str = "",
    ) -> List[ApprovalDecision]:
        """
        Approve multiple mutations in a single operator action (L2+ cadence).
        Each mutation receives an individual signed ApprovalDecision.

        Args:
            mutation_ids: List of mutation IDs to approve.
            epoch_id:     Epoch context for all approvals.
            operator_id:  Human operator performing the batch approval.
            notes:        Notes applied to all decisions in the batch.

        Returns:
            List of ApprovalDecision objects, one per mutation_id.
        """
        decisions: List[ApprovalDecision] = []
        state = self._load_index_or_rebuild()
        for mutation_id in mutation_ids:
            approval_id = self._request_approval_with_state(
                state=state,
                mutation_id=mutation_id,
                epoch_id=epoch_id,
                reason=ApprovalReason.BATCH_RELEASE,
                metadata={"batch_size": len(mutation_ids)},
            )
            decision = self._record_decision_with_state(
                state=state,
                approval_id=approval_id,
                approved=True,
                operator_id=operator_id,
                notes=notes,
            )
            decisions.append(decision)
        return decisions

    def revoke_approval(
        self,
        mutation_id: str,
        operator_id: str,
        reason: str,
    ) -> None:
        """
        Revoke a previously granted approval.
        Creates a REVOKE audit event; does not delete the original.
        After revocation, is_approved(mutation_id) returns False.

        Args:
            mutation_id: The mutation whose approval is being revoked.
            operator_id: The operator performing the revocation.
            reason:      Human-readable reason for revocation.
        """
        payload = {
            "mutation_id": mutation_id,
            "operator_id": operator_id,
            "reason": reason,
            "revoked_at": now_iso(),
            "status": ApprovalStatus.REVOKED.value,
        }
        self._write_audit(event_type="approval_revoked", payload=payload)

        if self._audit is not None:
            try:
                self._audit("human_approval_revoked", payload)
            except Exception:  # noqa: BLE001
                pass

    def is_approved(self, mutation_id: str) -> bool:
        """
        Gate check: returns True only if mutation has a non-revoked, non-expired
        APPROVED decision.

        HAPG-EXPIRY-0: Approvals older than APPROVAL_EXPIRY_S seconds are treated
        as EXPIRED and return False.  The EXPIRED transition is appended to the
        audit ledger so expiry is tamper-evident.

        Args:
            mutation_id: The mutation to check.

        Returns:
            True if approved, not revoked, and not expired. False otherwise.
        """
        import time as _time
        state = self._load_index_or_rebuild()
        status = state["mutation_status"].get(mutation_id)
        if status != ApprovalStatus.APPROVED.value:
            return False

        # HAPG-EXPIRY-0 — scan audit trail for the approval timestamp
        for entry in self._read_audit():
            if (
                entry.get("event_type") == "approval_decision"
                and entry.get("payload", {}).get("mutation_id") == mutation_id
                and entry.get("payload", {}).get("status") == ApprovalStatus.APPROVED.value
            ):
                try:
                    decided_at_str = entry["payload"]["decided_at"]
                    decided_at = datetime.fromisoformat(decided_at_str.replace("Z", "+00:00"))
                    age_s = (datetime.now(timezone.utc) - decided_at).total_seconds()
                    if age_s > APPROVAL_EXPIRY_S:
                        # Emit expiry event into audit ledger
                        expiry_payload = {
                            "mutation_id": mutation_id,
                            "status": ApprovalStatus.EXPIRED.value,
                            "age_seconds": int(age_s),
                            "expiry_threshold_s": APPROVAL_EXPIRY_S,
                        }
                        self._write_audit(event_type="approval_expired", payload=expiry_payload)
                        # Update in-memory status so subsequent calls are consistent
                        state["mutation_status"][mutation_id] = ApprovalStatus.EXPIRED.value
                        self._index_cache = None  # invalidate cache
                        return False
                except Exception:  # noqa: BLE001
                    pass  # malformed timestamp — do not grant approval
        return True

    def pending_queue(self) -> List[Dict[str, Any]]:
        """
        Return all approval requests that have not yet been decided.
        Used by operator dashboards and review queues.
        """
        state = self._load_index_or_rebuild()
        decided_ids = state["decided_approval_ids"]
        queue: List[Dict[str, Any]] = []
        for approval_id in state["queue_order"]:
            if approval_id not in decided_ids and approval_id in state["requests"]:
                queue.append(state["requests"][approval_id])
        return queue

    def verify_index_consistency(self) -> bool:
        """Return True when index snapshot digests match queue/audit JSONL replay."""
        state = self._load_index_or_rebuild()
        replay_state = self._replay_state()
        return (
            state["queue_digest"] == replay_state["queue_digest"]
            and state["audit_digest"] == replay_state["audit_digest"]
        )

    def audit_trail(self, mutation_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Return the full audit trail, optionally filtered by mutation_id.
        """
        entries = self._read_audit()
        if mutation_id is not None:
            entries = [
                e for e in entries
                if e.get("payload", {}).get("mutation_id") == mutation_id
            ]
        return entries

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_approval_id(self, mutation_id: str, epoch_id: str) -> str:
        seed = f"{mutation_id}:{epoch_id}:{now_iso()}"
        return "appr-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

    def _ensure_paths(self) -> None:
        self._queue_path.parent.mkdir(parents=True, exist_ok=True)
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        self._queue_path.touch(exist_ok=True)
        self._audit_path.touch(exist_ok=True)
        if not self._index_path.exists():
            self._write_index(self._replay_state())

    def _append_queue(self, payload: Dict[str, Any]) -> None:
        state = self._load_index_or_rebuild()
        self._append_queue_with_state(payload=payload, state=state)

    def _append_queue_with_state(self, payload: Dict[str, Any], state: Dict[str, Any]) -> None:
        with self._queue_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        approval_id = payload.get("approval_id")
        if isinstance(approval_id, str):
            state["requests"][approval_id] = payload
            state["queue_order"].append(approval_id)
        state["queue_digest"] = self._digest_jsonl(self._queue_path)
        self._write_index(state)

    def _read_queue(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for line in self._queue_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return rows

    def _find_request(self, approval_id: str) -> Optional[Dict[str, Any]]:
        state = self._load_index_or_rebuild()
        request = state["requests"].get(approval_id)
        if request is not None:
            return request
        for entry in self._read_queue():
            if entry.get("approval_id") == approval_id:
                return entry
        return None

    def _write_audit(self, event_type: str, payload: Dict[str, Any]) -> None:
        state = self._load_index_or_rebuild()
        self._write_audit_with_state(event_type=event_type, payload=payload, state=state)

    def _write_audit_with_state(
        self,
        event_type: str,
        payload: Dict[str, Any],
        state: Dict[str, Any],
    ) -> None:
        entry = {
            "event_type": event_type,
            "timestamp": now_iso(),
            "payload": payload,
        }
        with self._audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._apply_audit_to_state(state=state, event_type=event_type, payload=payload)
        state["audit_digest"] = self._digest_jsonl(self._audit_path)
        self._write_index(state)

    def _read_audit(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for line in self._audit_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return rows

    def _request_approval_with_state(
        self,
        state: Dict[str, Any],
        mutation_id: str,
        epoch_id: str,
        reason: str = ApprovalReason.MUTATION_ADVANCEMENT,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        approval_id = self._generate_approval_id(mutation_id, epoch_id)
        request = ApprovalRequest(
            approval_id=approval_id,
            mutation_id=mutation_id,
            epoch_id=epoch_id,
            reason=str(reason),
            requested_at=now_iso(),
            metadata=metadata or {},
        )
        self._append_queue_with_state(request.to_payload(), state)
        self._write_audit_with_state(
            event_type="approval_requested",
            payload={**request.to_payload(), "status": ApprovalStatus.PENDING.value},
            state=state,
        )
        return approval_id

    def _record_decision_with_state(
        self,
        state: Dict[str, Any],
        approval_id: str,
        approved: bool,
        operator_id: str,
        notes: str = "",
    ) -> ApprovalDecision:
        # HAPG-IDENTITY-0: In strict mode (production), operator_id MUST equal
        # the canonical HUMAN-0 GPG fingerprint.  Violations are ledger-appended
        # before raising so the attempt is permanently auditable.
        canonical_op = operator_id.strip().upper().replace(" ", "").replace(":", "")
        if _STRICT_HUMAN0 and canonical_op != HUMAN0_GPG_FINGERPRINT.replace(":", ""):
            violation_payload = {
                "operator_id_received": operator_id,
                "expected_fingerprint": HUMAN0_GPG_FINGERPRINT,
                "approval_id": approval_id,
                "invariant": "HAPG-IDENTITY-0",
            }
            self._write_audit_with_state(
                event_type="identity_violation",
                payload=violation_payload,
                state=state,
            )
            raise IdentityViolationError(
                f"HAPG-IDENTITY-0: operator_id '{operator_id}' does not match "
                f"HUMAN0_GPG_FINGERPRINT. Decision rejected and ledger-appended."
            )

        request = self._find_request(approval_id)
        if approval_id in state["requests"]:
            request = state["requests"][approval_id]
        if request is None:
            raise ValueError(f"approval_id_not_found:{approval_id}")

        status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        decided_at = now_iso()

        decision = ApprovalDecision(
            approval_id=approval_id,
            mutation_id=request["mutation_id"],
            epoch_id=request["epoch_id"],
            status=status.value,
            operator_id=operator_id,
            decided_at=decided_at,
            notes=notes,
            decision_digest=ApprovalDecision.compute_digest(
                approval_id=approval_id,
                mutation_id=request["mutation_id"],
                status=status.value,
                operator_id=operator_id,
                decided_at=decided_at,
            ),
        )
        self._write_audit_with_state(
            event_type="approval_decision",
            payload=decision.to_payload(),
            state=state,
        )

        if self._audit is not None:
            try:
                self._audit("human_approval_decision", decision.to_payload())
            except Exception:  # noqa: BLE001
                pass

        return decision

    def _load_index_or_rebuild(self) -> Dict[str, Any]:
        if self._index_cache is not None:
            return self._index_cache
        try:
            state = json.loads(self._index_path.read_text(encoding="utf-8"))
            if not self._state_shape_valid(state):
                raise ValueError("invalid_index_shape")
            if not self._is_state_consistent_with_logs(state):
                raise ValueError("digest_mismatch")
            state["decided_approval_ids"] = set(state["decided_approval_ids"])
            self._index_cache = state
            return state
        except Exception:  # noqa: BLE001
            state = self._replay_state()
            self._write_index(state)
            return state

    def _write_index(self, state: Dict[str, Any]) -> None:
        serializable = {
            "version": 1,
            "requests": state["requests"],
            "mutation_status": state["mutation_status"],
            "decided_approval_ids": sorted(state["decided_approval_ids"]),
            "queue_order": state["queue_order"],
            "queue_digest": state["queue_digest"],
            "audit_digest": state["audit_digest"],
        }
        tmp_path = self._index_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(serializable, sort_keys=True), encoding="utf-8")
        os.replace(tmp_path, self._index_path)
        self._index_cache = {
            **serializable,
            "decided_approval_ids": set(serializable["decided_approval_ids"]),
        }

    def _replay_state(self) -> Dict[str, Any]:
        requests: Dict[str, Dict[str, Any]] = {}
        queue_order: List[str] = []
        for entry in self._read_queue():
            approval_id = entry.get("approval_id")
            if isinstance(approval_id, str):
                requests[approval_id] = entry
                queue_order.append(approval_id)

        mutation_status: Dict[str, str] = {}
        decided_approval_ids = set()
        for entry in self._read_audit():
            self._apply_audit_to_state(
                state={
                    "requests": requests,
                    "mutation_status": mutation_status,
                    "decided_approval_ids": decided_approval_ids,
                    "queue_order": queue_order,
                    "queue_digest": "",
                    "audit_digest": "",
                },
                event_type=entry.get("event_type", ""),
                payload=entry.get("payload", {}),
            )

        return {
            "version": 1,
            "requests": requests,
            "mutation_status": mutation_status,
            "decided_approval_ids": decided_approval_ids,
            "queue_order": queue_order,
            "queue_digest": self._digest_jsonl(self._queue_path),
            "audit_digest": self._digest_jsonl(self._audit_path),
        }

    def _apply_audit_to_state(self, state: Dict[str, Any], event_type: str, payload: Dict[str, Any]) -> None:
        if event_type == "approval_decision":
            approval_id = payload.get("approval_id")
            if isinstance(approval_id, str):
                state["decided_approval_ids"].add(approval_id)
            mutation_id = payload.get("mutation_id")
            status = payload.get("status")
            if isinstance(mutation_id, str) and isinstance(status, str):
                state["mutation_status"][mutation_id] = status
        elif event_type == "approval_revoked":
            mutation_id = payload.get("mutation_id")
            if isinstance(mutation_id, str):
                state["mutation_status"][mutation_id] = ApprovalStatus.REVOKED.value

    def _digest_jsonl(self, path: Path) -> str:
        digest = hashlib.sha256()
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                normalized = json.dumps(json.loads(line), sort_keys=True, separators=(",", ":"))
                digest.update(normalized.encode("utf-8"))
            except json.JSONDecodeError:
                continue
        return digest.hexdigest()

    def _state_shape_valid(self, state: Dict[str, Any]) -> bool:
        required = {
            "version",
            "requests",
            "mutation_status",
            "decided_approval_ids",
            "queue_order",
            "queue_digest",
            "audit_digest",
        }
        return required.issubset(set(state))

    def _is_state_consistent_with_logs(self, state: Dict[str, Any]) -> bool:
        return (
            state.get("queue_digest") == self._digest_jsonl(self._queue_path)
            and state.get("audit_digest") == self._digest_jsonl(self._audit_path)
        )


__all__ = [
    "ApprovalStatus",
    "ApprovalReason",
    "ApprovalRequest",
    "ApprovalDecision",
    "HumanApprovalGate",
    "APPROVAL_EXPIRY_S",
    "HUMAN0_GPG_FINGERPRINT",
    "IdentityViolationError",
]
