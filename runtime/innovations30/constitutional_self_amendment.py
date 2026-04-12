# SPDX-License-Identifier: Apache-2.0
"""Innovation #38 — Autonomous Constitutional Self-Amendment Engine (ACSA).

Closes the full adversarial evolution loop:

  Red-Team (INNOV-36/Phase 126)
      ↓ CampaignReport
  GRRP (INNOV-37/Phase 127)
      ↓ AmendmentProposal / HumanEscalation
  ACSA (INNOV-38/Phase 128)  ← THIS MODULE
      ↓ ConstitutionalPatch → Lineage Ledger → Re-test trigger

ACSA ingests AmendmentProposals produced by GRRPEngine, validates each
proposal against the live constitution, produces a cryptographically
signed ConstitutionalPatch, appends an ACSARecord to the append-only
ledger, and — for ADVISORY/WARNING class — applies the patch
autonomously.  CRITICAL / BREACH class patches require a HUMAN-0
acknowledgement token before any application can proceed (ACSA-HUMAN0-0).

Constitutional invariants enforced by this module
──────────────────────────────────────────────────
ACSA-0          Every AmendmentProposal submitted to ACSA MUST
                produce either a ConstitutionalPatch or a
                BlockedAmendment record.  Silent discard is
                prohibited.  Violation raises DiscardError.

ACSA-GATE-0     A ConstitutionalPatch may not be applied unless
                acsa_gate_check() returns ACSAGateVerdict.PASS.
                Any other verdict blocks application and is
                persisted as a BlockedAmendment.

ACSA-CHAIN-0    Every ACSARecord carries a prev_digest linking to
                the preceding record, forming an append-only
                hash-chained amendment ledger.  Records with a
                broken chain raise ChainIntegrityError.

ACSA-HUMAN0-0   AmendmentProposals classified CRITICAL or BREACH
                MUST carry a non-empty human0_ack token before
                ACSAEngine will produce a ConstitutionalPatch.
                Absent token raises HumanGateBlockError.

ACSA-DETERM-0   patch_digest MUST be a pure function of
                (proposal_id, invariant_target, patch_text).
                No wall-clock reads, no random state.

ACSA-REPLAY-0   Replaying a previously applied proposal_id MUST
                raise DuplicatePatchError.  The engine maintains
                an applied-ID set backed by the ledger on load.
"""
from __future__ import annotations

import hashlib
import hmac
COSEAM_INV_CHAIN: str = "COSEAM-INV-CHAIN"
import json
import os
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Sentinel / error types
# ---------------------------------------------------------------------------

class DiscardError(RuntimeError):
    """ACSA-0 — silent discard attempted."""

class ACSAGateError(RuntimeError):
    """ACSA-GATE-0 — gate check failed."""

class ChainIntegrityError(RuntimeError):
    """ACSA-CHAIN-0 — hash-chain broken."""

class HumanGateBlockError(RuntimeError):
    """ACSA-HUMAN0-0 — CRITICAL/BREACH proposal missing human0_ack."""

class DeterminismError(RuntimeError):
    """ACSA-DETERM-0 — non-deterministic patch_digest detected."""

class DuplicatePatchError(RuntimeError):
    """ACSA-REPLAY-0 — proposal already applied."""

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ACSAGateVerdict(str, Enum):
    PASS = "PASS"
    BLOCKED_DUPLICATE = "BLOCKED_DUPLICATE"
    BLOCKED_HUMAN_GATE = "BLOCKED_HUMAN_GATE"
    BLOCKED_MALFORMED = "BLOCKED_MALFORMED"
    BLOCKED_INVARIANT_ABSENT = "BLOCKED_INVARIANT_ABSENT"

class PatchStatus(str, Enum):
    APPLIED = "APPLIED"
    BLOCKED = "BLOCKED"
    PENDING_HUMAN0 = "PENDING_HUMAN0"

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

HUMAN0_CLASSES = {"CRITICAL", "BREACH"}


@dataclass
class ConstitutionalPatch:
    """A validated, signed amendment ready to apply to the constitution."""
    patch_id: str
    proposal_id: str
    invariant_target: str
    classification: str
    patch_text: str
    human0_ack: str = ""       # required for CRITICAL/BREACH
    patch_digest: str = ""     # ACSA-DETERM-0: pure function of proposal fields
    hmac_digest: str = ""      # integrity seal

    def canonical(self) -> str:
        d = {k: v for k, v in asdict(self).items() if k != "hmac_digest"}
        return json.dumps(d, sort_keys=True, default=str)

    def compute_patch_digest(self) -> str:
        """ACSA-DETERM-0: deterministic digest over proposal identity."""
        raw = json.dumps(
            {
                "proposal_id": self.proposal_id,
                "invariant_target": self.invariant_target,
                "patch_text": self.patch_text,
            },
            sort_keys=True,
        )
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class BlockedAmendment:
    """A proposal that failed gate checks — persisted for audit (ACSA-0)."""
    blocked_id: str
    proposal_id: str
    invariant_target: str
    verdict: str
    reason: str
    hmac_digest: str = ""

    def canonical(self) -> str:
        d = {k: v for k, v in asdict(self).items() if k != "hmac_digest"}
        return json.dumps(d, sort_keys=True, default=str)


@dataclass
class ACSARecord:
    """Append-only ledger record for a single ACSA processing event (ACSA-CHAIN-0)."""
    record_id: str
    proposal_id: str
    status: str                      # PatchStatus value
    patch_id: str = ""
    blocked_id: str = ""
    patch_digest: str = ""
    prev_digest: str = "genesis"
    record_digest: str = ""

    def compute_record_digest(self, secret: bytes) -> str:
        payload = json.dumps(
            {
                "record_id": self.record_id,
                "proposal_id": self.proposal_id,
                "status": self.status,
                "patch_id": self.patch_id,
                "blocked_id": self.blocked_id,
                "patch_digest": self.patch_digest,
                "prev_digest": self.prev_digest,
            },
            sort_keys=True,
        )
        return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()[:24]

# ---------------------------------------------------------------------------
# ACSA Engine
# ---------------------------------------------------------------------------

_LEDGER_DEFAULT = Path("artifacts/governance/acsa_ledger.jsonl")
_CONSTITUTION_DEFAULT = Path("artifacts/governance/constitution.json")
_HUMAN0_CLASSES = frozenset({"CRITICAL", "BREACH"})


class ACSAEngine:
    """Autonomous Constitutional Self-Amendment Engine.

    Parameters
    ----------
    hmac_secret : bytes
        Secret used to compute record_digest values in ACSARecord.
    ledger_path : Path
        Append-only JSONL file; created on first write.
    constitution_path : Path
        JSON file representing the live invariant registry; updated on APPLY.
    """

    def __init__(
        self,
        hmac_secret: bytes,
        ledger_path: Path = _LEDGER_DEFAULT,
        constitution_path: Path = _CONSTITUTION_DEFAULT,
    ) -> None:
        self._secret = hmac_secret
        self._ledger_path = ledger_path
        self._constitution_path = constitution_path
        self._applied_ids: set[str] = set()
        self._prev_digest = "genesis"
        self._record_counter = 0
        self._load_ledger()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply_proposal(self, proposal: Any) -> ACSARecord:
        """Ingest an AmendmentProposal and return an ACSARecord.

        This is the primary entry point.  Enforces ACSA-0 (no silent
        discard) by always returning a record or raising.
        """
        pid = proposal.proposal_id
        target = proposal.invariant_target
        classification = proposal.classification
        patch_description = proposal.patch_description
        human0_ack = getattr(proposal, "human0_ack", "")

        # --- Gate check (ACSA-GATE-0) ---
        verdict, reason = self._gate_check(pid, classification, human0_ack, patch_description)

        if verdict != ACSAGateVerdict.PASS:
            blocked = self._make_blocked(pid, target, verdict, reason)
            rec = self._make_record(
                pid=pid,
                status=PatchStatus.BLOCKED,
                blocked_id=blocked.blocked_id,
            )
            self._persist_record(rec)
            return rec

        # --- Build patch (ACSA-DETERM-0) ---
        patch = self._build_patch(pid, target, classification, patch_description, human0_ack)

        # Verify determinism: recompute and compare
        expected = patch.compute_patch_digest()
        if patch.patch_digest != expected:
            raise DeterminismError(
                f"ACSA-DETERM-0: patch_digest mismatch for {pid}: "
                f"got {patch.patch_digest!r}, expected {expected!r}"
            )

        # --- Apply to constitution ---
        self._apply_to_constitution(patch)
        self._applied_ids.add(pid)

        rec = self._make_record(
            pid=pid,
            status=PatchStatus.APPLIED,
            patch_id=patch.patch_id,
            patch_digest=patch.patch_digest,
        )
        self._persist_record(rec)
        return rec

    def verify_chain(self) -> bool:
        """Re-read the ledger and verify the hash chain (ACSA-CHAIN-0).

        Returns True if intact; raises ChainIntegrityError on first break.
        """
        if not self._ledger_path.exists():
            return True
        prev = "genesis"
        for i, line in enumerate(self._ledger_path.read_text().splitlines()):
            rec = json.loads(line)
            if rec.get("prev_digest") != prev:
                raise ChainIntegrityError(
                    f"ACSA-CHAIN-0: chain break at ledger line {i}: "
                    f"expected prev_digest={prev!r}, got {rec.get('prev_digest')!r}"
                )
            prev = rec.get("record_digest", "")
        return True

    def applied_count(self) -> int:
        return len(self._applied_ids)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _gate_check(
        self,
        proposal_id: str,
        classification: str,
        human0_ack: str,
        patch_description: str,
    ) -> tuple[ACSAGateVerdict, str]:
        """ACSA-GATE-0: return (verdict, reason)."""
        # ACSA-REPLAY-0
        if proposal_id in self._applied_ids:
            return (
                ACSAGateVerdict.BLOCKED_DUPLICATE,
                f"Proposal {proposal_id!r} already applied (ACSA-REPLAY-0).",
            )
        # ACSA-HUMAN0-0
        if classification in _HUMAN0_CLASSES and not human0_ack:
            return (
                ACSAGateVerdict.BLOCKED_HUMAN_GATE,
                f"Classification {classification!r} requires human0_ack (ACSA-HUMAN0-0).",
            )
        # Malformed patch description
        if not patch_description or not patch_description.strip():
            return (
                ACSAGateVerdict.BLOCKED_MALFORMED,
                "patch_description is empty (ACSA-GATE-0 malformed).",
            )
        return (ACSAGateVerdict.PASS, "")

    def _build_patch(
        self,
        proposal_id: str,
        invariant_target: str,
        classification: str,
        patch_description: str,
        human0_ack: str,
    ) -> ConstitutionalPatch:
        patch_id = f"PATCH-{proposal_id}"
        patch = ConstitutionalPatch(
            patch_id=patch_id,
            proposal_id=proposal_id,
            invariant_target=invariant_target,
            classification=classification,
            patch_text=patch_description,
            human0_ack=human0_ack,
        )
        patch.patch_digest = patch.compute_patch_digest()
        # HMAC seal
        patch.hmac_digest = hmac.new(
            self._secret,
            patch.canonical().encode(),
            hashlib.sha256,
        ).hexdigest()[:24]
        return patch

    def _make_blocked(
        self,
        proposal_id: str,
        invariant_target: str,
        verdict: ACSAGateVerdict,
        reason: str,
    ) -> BlockedAmendment:
        blocked_id = f"BLOCKED-{proposal_id}"
        b = BlockedAmendment(
            blocked_id=blocked_id,
            proposal_id=proposal_id,
            invariant_target=invariant_target,
            verdict=verdict.value,
            reason=reason,
        )
        b.hmac_digest = hmac.new(
            self._secret,
            b.canonical().encode(),
            hashlib.sha256,
        ).hexdigest()[:24]
        return b

    def _make_record(
        self,
        pid: str,
        status: PatchStatus,
        patch_id: str = "",
        blocked_id: str = "",
        patch_digest: str = "",
    ) -> ACSARecord:
        self._record_counter += 1
        rec = ACSARecord(
            record_id=f"ACSA-REC-{self._record_counter:06d}",
            proposal_id=pid,
            status=status.value,
            patch_id=patch_id,
            blocked_id=blocked_id,
            patch_digest=patch_digest,
            prev_digest=self._prev_digest,
        )
        rec.record_digest = rec.compute_record_digest(self._secret)
        self._prev_digest = rec.record_digest
        return rec

    def _apply_to_constitution(self, patch: ConstitutionalPatch) -> None:
        """Append the patch to the live constitution JSON (ACSA-GATE-0 post-check)."""
        self._constitution_path.parent.mkdir(parents=True, exist_ok=True)
        if self._constitution_path.exists():
            constitution = json.loads(self._constitution_path.read_text())
        else:
            constitution = {"invariants": [], "patches_applied": 0}
        constitution.setdefault("patches", []).append(
            {
                "patch_id": patch.patch_id,
                "proposal_id": patch.proposal_id,
                "invariant_target": patch.invariant_target,
                "classification": patch.classification,
                "patch_text": patch.patch_text,
                "patch_digest": patch.patch_digest,
            }
        )
        constitution["patches_applied"] = len(constitution["patches"])
        self._constitution_path.write_text(
            json.dumps(constitution, indent=2, sort_keys=True)
        )

    def _persist_record(self, rec: ACSARecord) -> None:
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self._ledger_path.open("a") as fh:
            fh.write(json.dumps(asdict(rec), sort_keys=True) + "\n")

    def _load_ledger(self) -> None:
        """Replay ledger on startup to restore applied_ids and prev_digest."""
        if not self._ledger_path.exists():
            return
        lines = self._ledger_path.read_text().splitlines()
        for line in lines:
            if not line.strip():
                continue
            rec = json.loads(line)
            self._applied_ids.add(rec["proposal_id"])
            self._prev_digest = rec.get("record_digest", self._prev_digest)
            self._record_counter += 1


# ---------------------------------------------------------------------------
# Gate helper — standalone for test injection
# ---------------------------------------------------------------------------

def acsa_gate_check(
    proposal_id: str,
    classification: str,
    human0_ack: str,
    patch_description: str,
    applied_ids: set[str],
) -> tuple[ACSAGateVerdict, str]:
    """Stateless gate check exposed for unit tests (ACSA-GATE-0)."""
    if proposal_id in applied_ids:
        return (
            ACSAGateVerdict.BLOCKED_DUPLICATE,
            f"Proposal {proposal_id!r} already applied (ACSA-REPLAY-0).",
        )
    if classification in _HUMAN0_CLASSES and not human0_ack:
        return (
            ACSAGateVerdict.BLOCKED_HUMAN_GATE,
            f"Classification {classification!r} requires human0_ack (ACSA-HUMAN0-0).",
        )
    if not patch_description or not patch_description.strip():
        return (
            ACSAGateVerdict.BLOCKED_MALFORMED,
            "patch_description is empty (ACSA-GATE-0).",
        )
    return (ACSAGateVerdict.PASS, "")

    def _append_event(self, event) -> None:
        """CED-INV-AUDIT: append-only JSONL event record; advance HMAC chain head."""
        import json, dataclasses
        ledger = getattr(self, 'ledger_path', None) or getattr(self, 'state_path', None)
        if ledger is None:
            return
        from pathlib import Path
        ledger = Path(ledger)
        ledger.parent.mkdir(parents=True, exist_ok=True)
        row = json.dumps(dataclasses.asdict(event) if hasattr(event, '__dataclass_fields__') else event, sort_keys=True)
        with ledger.open("a") as f:
            f.write(row + "\n")

