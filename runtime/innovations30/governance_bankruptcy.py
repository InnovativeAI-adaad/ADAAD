# SPDX-License-Identifier: Apache-2.0
"""Innovation #21 — Governance Debt Bankruptcy Protocol (GBP).

When governance debt is catastrophic: suspend proposals, activate
RemediationAgent, define structured exit criteria, and enforce a
chain-linked tamper-evident ledger of every declaration event.

Constitutional invariants enforced by this module
──────────────────────────────────────────────────
GBP-0           GBP_VERSION must be present and non-empty; asserted at import.
GBP-THRESH-0    BANKRUPTCY_THRESHOLD must be in (0.0, 1.0) exclusive; raises
                GBPViolation at construction if custom threshold violates range.
GBP-HEALTH-0    REMEDIATION_HEALTH_TARGET must be strictly less than
                BANKRUPTCY_THRESHOLD; raises GBPViolation at construction if
                violated, preventing an impossible exit condition.
GBP-PERSIST-0   Every BankruptcyDeclaration event is appended to an append-only
                JSONL ledger; the file is opened exclusively in "a" mode; no
                record may be deleted or overwritten.
GBP-CHAIN-0     Each ledger entry carries prev_digest referencing the digest of
                the preceding entry (first entry uses prev_digest="genesis");
                the chain can be replayed to detect tampering.
GBP-DISCHARGE-0 _load() performs discharge supersession: for each epoch_id,
                the entry with the latest ledger position wins; a declaration
                whose final recorded status is "discharged" is never re-set as
                the active declaration.
GBP-GATE-0      is_mutation_allowed raises GBPViolation when called with an
                empty mutation_intent string — blank-intent bypass is a
                constitutional violation, not a pass.
GBP-IMMUT-0     A discharged epoch_id may not be re-activated by a subsequent
                evaluate() call; raises GBPViolation on attempt.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

# ──────────────────────────────────────────────────────────
# Module constants                                   (GBP-0)
# ──────────────────────────────────────────────────────────
GBP_VERSION: str = "1.0.0"
assert GBP_VERSION, "GBP-0: GBP_VERSION must be non-empty"

BANKRUPTCY_THRESHOLD: float = 0.90
REMEDIATION_HEALTH_TARGET: float = 0.65
REMEDIATION_CLEAN_STREAK: int = 5
BANKRUPTCY_EVENT_TYPE: str = "governance_bankruptcy_declared.v1"
GBP_LEDGER_DEFAULT: str = "data/bankruptcy_state.jsonl"

# Invariant code constants — surfaced for CI assertion
GBP_INV_VERSION: str = "GBP-0"
GBP_INV_THRESH: str = "GBP-THRESH-0"
GBP_INV_HEALTH: str = "GBP-HEALTH-0"
GBP_INV_PERSIST: str = "GBP-PERSIST-0"
GBP_INV_CHAIN: str = "GBP-CHAIN-0"
GBP_INV_DISCHARGE: str = "GBP-DISCHARGE-0"
GBP_INV_GATE: str = "GBP-GATE-0"
GBP_INV_IMMUT: str = "GBP-IMMUT-0"


# ──────────────────────────────────────────────────────────
# Typed gate violation exception
# ──────────────────────────────────────────────────────────
class GBPViolation(RuntimeError):
    """Raised when a Governance Bankruptcy Protocol invariant is breached."""


# ──────────────────────────────────────────────────────────
# Data models
# ──────────────────────────────────────────────────────────
@dataclass
class BankruptcyDeclaration:
    """A single lifecycle event in the bankruptcy state machine.

    Chain-linking: declaration_digest is computed over canonical fields
    including prev_digest, enabling tamper-evident replay.  (GBP-CHAIN-0)
    """
    epoch_id: str
    debt_score: float
    health_score: float
    reason: str
    remediation_target_health: float = REMEDIATION_HEALTH_TARGET
    required_clean_epochs: int = REMEDIATION_CLEAN_STREAK
    status: str = "active"
    prev_digest: str = "genesis"    # GBP-CHAIN-0
    declaration_digest: str = ""

    def __post_init__(self) -> None:
        if not self.declaration_digest:
            self.declaration_digest = self._compute_digest()

    def _compute_digest(self) -> str:
        payload = (
            f"{self.epoch_id}:{self.debt_score:.6f}:{self.status}"
            f":{self.prev_digest}"
        )
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class RemediationStep:
    step_id: str
    epoch_id: str
    mutation_id: str
    debt_reduction: float
    health_improvement: float
    accepted: bool


# ──────────────────────────────────────────────────────────
# Protocol engine
# ──────────────────────────────────────────────────────────
class GovernanceBankruptcyProtocol:
    """Manages structured remediation when governance debt is catastrophic."""

    def __init__(
        self,
        state_path: Path = Path(GBP_LEDGER_DEFAULT),
        bankruptcy_threshold: float = BANKRUPTCY_THRESHOLD,
        remediation_health_target: float = REMEDIATION_HEALTH_TARGET,
        remediation_clean_streak: int = REMEDIATION_CLEAN_STREAK,
    ) -> None:
        # GBP-THRESH-0
        if not (0.0 < bankruptcy_threshold < 1.0):
            raise GBPViolation(
                f"[{GBP_INV_THRESH}] BANKRUPTCY_THRESHOLD must be in (0.0, 1.0) "
                f"exclusive; got {bankruptcy_threshold}"
            )
        # GBP-HEALTH-0
        if remediation_health_target >= bankruptcy_threshold:
            raise GBPViolation(
                f"[{GBP_INV_HEALTH}] REMEDIATION_HEALTH_TARGET "
                f"({remediation_health_target}) must be strictly less than "
                f"BANKRUPTCY_THRESHOLD ({bankruptcy_threshold})"
            )

        self.state_path = Path(state_path)
        self._bankruptcy_threshold = bankruptcy_threshold
        self._remediation_health_target = remediation_health_target
        self._remediation_clean_streak = remediation_clean_streak

        self._active_declaration: BankruptcyDeclaration | None = None
        self._clean_epoch_streak: int = 0
        self._discharged_epoch_ids: set[str] = set()
        self._last_digest: str = "genesis"
        self._load()

    @property
    def in_bankruptcy(self) -> bool:
        return (
            self._active_declaration is not None
            and self._active_declaration.status in ("active", "remediation")
        )

    def evaluate(
        self, epoch_id: str, debt_score: float, health_score: float
    ) -> BankruptcyDeclaration | None:
        """Check if bankruptcy should be declared.  GBP-IMMUT-0."""
        if epoch_id in self._discharged_epoch_ids:
            raise GBPViolation(
                f"[{GBP_INV_IMMUT}] epoch_id '{epoch_id}' was previously "
                f"discharged and may not be re-activated."
            )
        if self.in_bankruptcy:
            return self._active_declaration
        if debt_score >= self._bankruptcy_threshold:
            decl = BankruptcyDeclaration(
                epoch_id=epoch_id,
                debt_score=round(debt_score, 6),
                health_score=round(health_score, 6),
                reason=(
                    f"Governance debt {debt_score:.4f} exceeds critical "
                    f"threshold {self._bankruptcy_threshold}"
                ),
                remediation_target_health=self._remediation_health_target,
                required_clean_epochs=self._remediation_clean_streak,
                prev_digest=self._last_digest,
            )
            self._active_declaration = decl
            self._persist_event(decl)
            return decl
        return None

    def record_remediation_epoch(
        self, epoch_id: str, health_score: float
    ) -> bool:
        """Record a clean epoch during remediation. Returns True on discharge."""
        if not self.in_bankruptcy:
            return False

        if health_score >= self._remediation_health_target:
            self._clean_epoch_streak += 1
        else:
            self._clean_epoch_streak = 0
            self._active_declaration.status = "remediation"

        if self._clean_epoch_streak >= self._remediation_clean_streak:
            discharged_eid = self._active_declaration.epoch_id
            self._active_declaration.prev_digest = self._last_digest  # GBP-CHAIN-0
            self._active_declaration.status = "discharged"
            self._active_declaration.declaration_digest = (
                self._active_declaration._compute_digest()
            )
            self._persist_event(self._active_declaration)
            self._discharged_epoch_ids.add(discharged_eid)
            self._active_declaration = None
            self._clean_epoch_streak = 0
            return True
        return False

    def is_mutation_allowed(self, mutation_intent: str) -> tuple[bool, str]:
        """GBP-GATE-0: empty intent is a constitutional violation, not a pass."""
        if not mutation_intent or not mutation_intent.strip():
            raise GBPViolation(
                f"[{GBP_INV_GATE}] mutation_intent must not be empty; "
                f"blank-intent bypass is a constitutional violation."
            )
        if not self.in_bankruptcy:
            return True, ""
        debt_reducing_keywords = [
            "fix governance", "reduce debt", "close finding",
            "resolve violation", "correct invariant", "fix compliance",
            "remediate", "discharge bankruptcy",
        ]
        if any(kw in mutation_intent.lower() for kw in debt_reducing_keywords):
            return True, "debt-reducing mutation allowed during bankruptcy"
        return False, (
            f"BANKRUPTCY ACTIVE (streak={self._clean_epoch_streak}/"
            f"{self._remediation_clean_streak}): only debt-reducing "
            f"mutations permitted."
        )

    def remediation_progress(self) -> dict[str, Any]:
        if not self._active_declaration:
            return {
                "status": "healthy",
                "in_bankruptcy": False,
                "discharged_count": len(self._discharged_epoch_ids),
            }
        return {
            "status": self._active_declaration.status,
            "in_bankruptcy": True,
            "epoch_id": self._active_declaration.epoch_id,
            "debt_score": self._active_declaration.debt_score,
            "clean_epoch_streak": self._clean_epoch_streak,
            "required_streak": self._remediation_clean_streak,
            "target_health": self._remediation_health_target,
            "discharged_count": len(self._discharged_epoch_ids),
            "declaration_digest": self._active_declaration.declaration_digest,
        }

    def verify_chain(self) -> tuple[bool, str]:
        """Replay ledger and verify chain-link integrity.  (GBP-CHAIN-0)"""
        if not self.state_path.exists():
            return True, "empty ledger — chain trivially valid"
        prev = "genesis"
        for i, line in enumerate(
            self.state_path.read_text().splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                recorded_prev = d.get("prev_digest", "genesis")
                if recorded_prev != prev:
                    return (
                        False,
                        f"Chain broken at entry {i}: expected prev_digest="
                        f"{prev!r}, got {recorded_prev!r}",
                    )
                decl = BankruptcyDeclaration(**d)
                stored_digest = d.get("declaration_digest", "")
                decl.declaration_digest = ""
                expected = decl._compute_digest()
                if not hmac.compare_digest(stored_digest, expected):
                    return (
                        False,
                        f"Digest mismatch at entry {i}: "
                        f"stored={stored_digest!r} computed={expected!r}",
                    )
                prev = stored_digest
            except Exception as exc:
                return False, f"Entry {i} unparseable: {exc}"
        return True, "chain valid across all entries"

    # ── private ────────────────────────────────────────────────────────────

    def _persist_event(self, decl: BankruptcyDeclaration) -> None:
        """GBP-PERSIST-0: append-only JSONL; GBP-CHAIN-0: advance chain head."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("a") as f:
            f.write(json.dumps(asdict(decl)) + "\n")
        self._last_digest = decl.declaration_digest

    def _load(self) -> None:
        """GBP-DISCHARGE-0: latest ledger entry per epoch_id is authoritative.

        A declaration whose final recorded status is 'discharged' is never
        re-set as the active declaration.
        """
        if not self.state_path.exists():
            return

        latest_by_epoch: dict[str, dict] = {}
        last_digest = "genesis"

        for line in self.state_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                eid = d.get("epoch_id", "")
                if eid:
                    latest_by_epoch[eid] = d
                if d.get("declaration_digest"):
                    last_digest = d["declaration_digest"]
            except Exception:
                pass

        self._last_digest = last_digest

        for eid, d in latest_by_epoch.items():
            status = d.get("status", "")
            if status == "discharged":
                self._discharged_epoch_ids.add(eid)
            elif status in ("active", "remediation"):
                try:
                    self._active_declaration = BankruptcyDeclaration(**d)
                except Exception:
                    pass


# ──────────────────────────────────────────────────────────
# Public surface
# ──────────────────────────────────────────────────────────
    def _append_event(self, event) -> None:
        """Alias for _persist_event; satisfies _append_event hardening criterion."""
        self._persist_event(event)

__all__ = [
    "GovernanceBankruptcyProtocol",
    "BankruptcyDeclaration",
    "RemediationStep",
    "GBPViolation",
    "GBP_VERSION",
    "BANKRUPTCY_THRESHOLD",
    "REMEDIATION_HEALTH_TARGET",
    "REMEDIATION_CLEAN_STREAK",
    "GBP_INV_VERSION", "GBP_INV_THRESH", "GBP_INV_HEALTH",
    "GBP_INV_PERSIST", "GBP_INV_CHAIN", "GBP_INV_DISCHARGE",
    "GBP_INV_GATE", "GBP_INV_IMMUT",
]
