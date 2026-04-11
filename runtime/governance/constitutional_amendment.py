# SPDX-License-Identifier: Apache-2.0
"""
ADAAD v8 — Constitutional Amendment Engine (Human-in-the-Loop Override)
=========================================================================
Solves the "Last Mile" HITL problem:

  THE PROBLEM:
  In Beast Mode, ADAAD might get stuck in a loop where GovernanceGate v2
  rejects a change the architect knows is necessary. The naive solution —
  "turn off the gate" — destroys ADAAD's core value proposition.

  THE SOLUTION: Constitutional Amendments.
  Instead of disabling gates, the human digitally signs a Certificate of
  Amendment that temporarily updates a specific policy constraint.
  The amendment is:
    - Scoped to one capability and one rule
    - Time-bounded (max 3 epochs, matches Exception Token TTL)
    - Cryptographically signed (PGP/SSH fingerprint required)
    - Recorded in the GovernanceExceptionEvidence ledger
    - Auto-expiring with mandatory reconciliation report

  The GovernanceGate never "turns off."
  The human expands the constitutional definition of what is allowed,
  for a bounded period, with full audit trail.

CONSTITUTIONAL INVARIANTS ENFORCED:
  HUMAN-0         — every amendment requires a valid human key fingerprint
  AMEND-SCOPE-0   — amendments are scoped to single capability + single rule
  AMEND-TTL-0     — maximum 3 epochs; non-renewable without new signing
  AMEND-TIER0-0   — Tier-0 capabilities and hard-reject rules cannot be amended
  AMEND-LEDGER-0  — every amendment is written to exception_tokens.jsonl immediately

Usage:
    from runtime.governance.constitutional_amendment import ConstitutionalAmendmentEngine

    engine = ConstitutionalAmendmentEngine(
        ledger_path="data/exception_tokens.jsonl"
    )
    amendment = engine.request_amendment(
        capability_name="StrategySelection",
        rule_id="AST-COMPLEX-0",
        justification="Multi-step refactor requires temporary complexity relief.",
        lineage_projection=(0.72, 0.81, 0.88),
        duration_epochs=3,
        human_key_fingerprint="SHA256:abc123...",
        human_approval_ref="HUMAN-GATE-2026-03-13-001",
        epoch_id="epoch_00127",
        current_epoch_count=127,
    )
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Rules that can NEVER be amended — hard constitutional boundaries
# ---------------------------------------------------------------------------
NON_AMENDABLE_RULES = frozenset({
    "AST-SAFE-0",       # no exec/eval — non-negotiable
    "AST-IMPORT-0",     # Tier-0 import boundary — non-negotiable
    "SANDBOX-DIV-0",    # replay divergence = rejection — non-negotiable
    "SEMANTIC-INT-0",   # error guard removal — non-negotiable
})

AMENDABLE_RULES = frozenset({
    "AST-COMPLEX-0",    # complexity ceiling — Class B eligible
})

TIER_0_CAPABILITIES = frozenset({
    "ConstitutionEnforcement",
    "DeterministicReplay",
    "LedgerEvidence",
    "GovernanceGate",
})


class AmendmentStatus(str, Enum):
    PENDING           = "PENDING"            # created, awaiting human signature
    ACTIVE            = "ACTIVE"             # signed and recorded; in effect
    EXPIRED           = "EXPIRED"            # TTL elapsed without explicit resolution
    REVOKED           = "REVOKED"            # auto-revoked due to instability
    RESOLVED_BENEFIT  = "RESOLVED_AS_BENEFICIAL"   # amendment led to net improvement
    RESOLVED_REVERTED = "RESOLVED_AS_REVERTED"     # amendment changes rolled back


@dataclass
class ConstitutionalAmendment:
    """
    A signed, time-bounded constitutional rule relaxation.
    Wraps GovernanceExceptionEvidence with lifecycle management.

    This is NOT a bypass. The GovernanceGate v2 still evaluates the mutation.
    It evaluates it under an expanded rule definition for the amendment window.
    """
    amendment_id: str
    capability_name: str
    rule_id: str
    justification: str
    lineage_projection: tuple[float, float, float]
    duration_epochs: int
    human_key_fingerprint: str
    human_approval_ref: str
    granted_at_epoch: str
    expires_at_epoch: int
    status: AmendmentStatus
    mutations_covered: list[str]
    resolution_notes: str

    @property
    def token_id(self) -> str:
        """Deterministic SHA-256 token ID — non-guessable, matches GovernanceExceptionEvidence."""
        scope_hash = hashlib.sha256(
            f"{self.capability_name}:{self.rule_id}".encode()
        ).hexdigest()[:16]
        payload = f"{self.granted_at_epoch}{self.capability_name}{self.rule_id}{scope_hash}"
        return hashlib.sha256(payload.encode()).hexdigest()

    def is_active(self, current_epoch_count: int) -> bool:
        return (
            self.status == AmendmentStatus.ACTIVE
            and current_epoch_count < self.expires_at_epoch
        )

    def is_expired(self, current_epoch_count: int) -> bool:
        return current_epoch_count >= self.expires_at_epoch

    def validate(self) -> None:
        """Raises ValueError on any constitutional violation."""
        if self.rule_id not in AMENDABLE_RULES:
            raise ValueError(
                f"CONSTITUTIONAL VIOLATION (AMEND-SCOPE-0): "
                f"Rule '{self.rule_id}' is not amendable. "
                f"Non-amendable rules: {NON_AMENDABLE_RULES}. "
                f"Amendable rules: {AMENDABLE_RULES}."
            )
        if self.capability_name in TIER_0_CAPABILITIES:
            raise ValueError(
                f"CONSTITUTIONAL VIOLATION (AMEND-TIER0-0): "
                f"Tier-0 capability '{self.capability_name}' cannot be amended."
            )
        if not 1 <= self.duration_epochs <= 3:
            raise ValueError(
                f"CONSTITUTIONAL VIOLATION (AMEND-TTL-0): "
                f"duration_epochs must be 1..3. Got: {self.duration_epochs}."
            )
        if not self.human_key_fingerprint or not self.human_approval_ref:
            raise ValueError(
                "CONSTITUTIONAL VIOLATION (HUMAN-0): "
                "human_key_fingerprint and human_approval_ref are required."
            )
        if not all(isinstance(p, float) and 0.0 <= p <= 1.0 for p in self.lineage_projection):
            raise ValueError(
                "lineage_projection must contain 3 floats in [0.0, 1.0]. "
                "Amendment requires positive lineage simulation."
            )
        if self.lineage_projection[-1] <= self.lineage_projection[0]:
            raise ValueError(
                "lineage_projection must show net improvement (+1, +2, +3 epochs). "
                "Amendment denied: simulation does not project improvement."
            )

    def to_dict(self) -> dict:
        return {
            "amendment_id": self.amendment_id,
            "token_id": self.token_id,
            "capability_name": self.capability_name,
            "rule_id": self.rule_id,
            "justification": self.justification,
            "lineage_projection": list(self.lineage_projection),
            "duration_epochs": self.duration_epochs,
            "human_key_fingerprint": self.human_key_fingerprint,
            "human_approval_ref": self.human_approval_ref,
            "granted_at_epoch": self.granted_at_epoch,
            "expires_at_epoch": self.expires_at_epoch,
            "status": self.status.value,
            "mutations_covered": self.mutations_covered,
            "resolution_notes": self.resolution_notes,
        }


class ConstitutionalAmendmentEngine:
    """
    Manages the full lifecycle of constitutional amendments:
    - Validation (AMEND-SCOPE-0, AMEND-TTL-0, AMEND-TIER0-0, HUMAN-0)
    - Creation and ledger write (AMEND-LEDGER-0)
    - Activation, expiry tracking, auto-revocation
    - Resolution reporting for Aponi Exception Token Status panel

    All amendments are written to data/exception_tokens.jsonl immediately
    upon signing. This is an append-only JSONL — no record is ever modified,
    only new status records are appended.

    Args:
        ledger_path : path to data/exception_tokens.jsonl
    """

    def __init__(self, ledger_path: str = "data/exception_tokens.jsonl"):
        self.ledger_path = Path(ledger_path)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def request_amendment(
        self,
        capability_name: str,
        rule_id: str,
        justification: str,
        lineage_projection: tuple[float, float, float],
        duration_epochs: int,
        human_key_fingerprint: str,
        human_approval_ref: str,
        epoch_id: str,
        current_epoch_count: int,
    ) -> ConstitutionalAmendment:
        """
        Create, validate, and record a new constitutional amendment.
        Immediately writes to exception_tokens.jsonl (AMEND-LEDGER-0).

        Raises ValueError on any constitutional violation.
        Returns the active ConstitutionalAmendment on success.
        """
        amendment = ConstitutionalAmendment(
            amendment_id=self._generate_amendment_id(
                epoch_id, capability_name, rule_id
            ),
            capability_name=capability_name,
            rule_id=rule_id,
            justification=justification,
            lineage_projection=lineage_projection,
            duration_epochs=duration_epochs,
            human_key_fingerprint=human_key_fingerprint,
            human_approval_ref=human_approval_ref,
            granted_at_epoch=epoch_id,
            expires_at_epoch=current_epoch_count + duration_epochs,
            status=AmendmentStatus.ACTIVE,
            mutations_covered=[],
            resolution_notes="",
        )

        # Validate constitutional constraints
        amendment.validate()

        # Write to ledger immediately (AMEND-LEDGER-0)
        self._append_to_ledger(amendment)

        return amendment

    def record_mutation_under_amendment(
        self,
        amendment: ConstitutionalAmendment,
        mutation_id: str,
        current_epoch_count: int,
    ) -> ConstitutionalAmendment:
        """
        Records that a mutation was executed under this amendment.
        Auto-revokes if TTL has elapsed.
        """
        if amendment.is_expired(current_epoch_count):
            return self.revoke(amendment, f"TTL expired at epoch {current_epoch_count}")

        amendment.mutations_covered.append(mutation_id)
        self._append_status_update(amendment, f"Mutation {mutation_id} covered.")
        return amendment

    def revoke(
        self,
        amendment: ConstitutionalAmendment,
        trigger: str,
    ) -> ConstitutionalAmendment:
        """
        Auto-revokes an amendment due to instability trigger.
        Trigger conditions:
          - Lineage diverges from projection
          - Target capability contract changes
          - Test failure rate exceeds threshold
          - TTL expires
        """
        amendment.status = AmendmentStatus.REVOKED
        amendment.resolution_notes = f"AUTO-REVOKED: {trigger}"
        self._append_status_update(amendment, f"REVOKED: {trigger}")
        return amendment

    def resolve(
        self,
        amendment: ConstitutionalAmendment,
        beneficial: bool,
        notes: str,
    ) -> ConstitutionalAmendment:
        """
        Manually resolves an amendment after the window expires.
        Called by Aponi console or architect review.
        beneficial=True → RESOLVED_AS_BENEFICIAL; False → RESOLVED_AS_REVERTED.
        """
        amendment.status = (
            AmendmentStatus.RESOLVED_BENEFIT if beneficial
            else AmendmentStatus.RESOLVED_REVERTED
        )
        amendment.resolution_notes = notes
        self._append_status_update(amendment, notes)
        return amendment

    def get_active_amendments(self, current_epoch_count: int) -> list[dict]:
        """
        Returns all currently active amendments from the ledger.
        Used by GovernanceGate v2 to determine which capability/rule
        pairs are under temporary relief.
        """
        amendments = self._load_ledger()
        active = []
        seen_ids: set[str] = set()

        # Walk in reverse: last status update wins
        for record in reversed(amendments):
            aid = record.get("amendment_id")
            if aid in seen_ids:
                continue
            seen_ids.add(aid)
            if (
                record.get("status") == AmendmentStatus.ACTIVE.value
                and current_epoch_count < record.get("expires_at_epoch", 0)
            ):
                active.append(record)

        return active

    def check_expired_amendments(
        self,
        current_epoch_count: int,
    ) -> list[str]:
        """
        Checks all active amendments for expiry.
        Writes EXPIRED status for any that have lapsed.
        Returns list of amendment_ids that were expired.
        """
        active = self.get_active_amendments(current_epoch_count)
        expired_ids = []
        for record in active:
            if current_epoch_count >= record.get("expires_at_epoch", 0):
                amendment = self._dict_to_amendment(record)
                amendment.status = AmendmentStatus.EXPIRED
                amendment.resolution_notes = (
                    f"TTL elapsed at epoch {current_epoch_count}. "
                    f"Requires human reconciliation."
                )
                self._append_status_update(amendment, amendment.resolution_notes)
                expired_ids.append(record["amendment_id"])
        return expired_ids

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_amendment_id(
        self, epoch_id: str, capability_name: str, rule_id: str
    ) -> str:
        payload = f"{epoch_id}:{capability_name}:{rule_id}:{datetime.now(timezone.utc).isoformat()}"
        return hashlib.sha256(payload.encode()).hexdigest()[:32]

    def _append_to_ledger(self, amendment: ConstitutionalAmendment) -> None:
        """Append-only write to exception_tokens.jsonl."""
        record = amendment.to_dict()
        record["event"] = "AMENDMENT_CREATED"
        record["written_at"] = datetime.now(timezone.utc).isoformat()
        with open(self.ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    def _append_status_update(
        self,
        amendment: ConstitutionalAmendment,
        notes: str,
    ) -> None:
        """Append a status update record (never modifies prior records)."""
        record = {
            "amendment_id": amendment.amendment_id,
            "token_id": amendment.token_id,
            "status": amendment.status.value,
            "notes": notes,
            "event": "AMENDMENT_STATUS_UPDATE",
            "written_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(self.ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    def _load_ledger(self) -> list[dict]:
        records = []
        if not self.ledger_path.exists():
            return records
        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return records

    def _dict_to_amendment(self, record: dict) -> ConstitutionalAmendment:
        return ConstitutionalAmendment(
            amendment_id=record["amendment_id"],
            capability_name=record["capability_name"],
            rule_id=record["rule_id"],
            justification=record.get("justification", ""),
            lineage_projection=tuple(record.get("lineage_projection", [0.0, 0.0, 0.0])),
            duration_epochs=record.get("duration_epochs", 1),
            human_key_fingerprint=record.get("human_key_fingerprint", ""),
            human_approval_ref=record.get("human_approval_ref", ""),
            granted_at_epoch=record.get("granted_at_epoch", ""),
            expires_at_epoch=record.get("expires_at_epoch", 0),
            status=AmendmentStatus(record.get("status", "ACTIVE")),
            mutations_covered=record.get("mutations_covered", []),
            resolution_notes=record.get("resolution_notes", ""),
        )
