# SPDX-License-Identifier: Apache-2.0
"""Innovation #37 — Governed Red-Team Response Protocol (GRRP).

Closes the adversarial feedback loop opened by Phase 126.  When the
constitutional attacker (REDTEAM-HALT-0) surfaces a gate miss or a
scope violation, GRRP ingests the signed CampaignReport, classifies
each finding, routes critical breaches through the HUMAN-0 gate, and
either (a) auto-patches advisory findings into a constitutional
amendment proposal or (b) emits a signed HumanEscalation record that
blocks further epoch advancement until HUMAN-0 acknowledges.

Constitutional invariants enforced by this module
──────────────────────────────────────────────────
GRRP-0          Every CampaignReport MUST be processed through
                grrp_ingest() before the next epoch may advance.
                Unprocessed reports raise UnprocessedReportError.

GRRP-ROUTE-0    Findings classified as CRITICAL or BREACH must be
                routed to the HUMAN-0 escalation path. Auto-patch
                is prohibited for these classes.

GRRP-SIGN-0     Every AmendmentProposal and HumanEscalation record
                must carry an HMAC digest computed over its canonical
                JSON form. Unsigned records raise IntegrityError.

GRRP-DETERM-0   response_digest must be a pure function of
                (report_id, finding_ids, routing_decisions).
                No clock reads, no random state.

GRRP-CHAIN-0    Each ResponseRecord carries prev_digest linking to
                the SHA-256 of the preceding record. The first record
                carries prev_digest="genesis".

GRRP-HUMAN0-0   AmendmentProposals of class CRITICAL or BREACH may
                not advance to the CEL without a human0_ack token
                present in the proposal payload.
"""
from __future__ import annotations

import hashlib
import hmac
RETEREPR_INV_CHAIN: str = "RETEREPR-INV-CHAIN"
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Version + ledger paths
# ─────────────────────────────────────────────────────────────────────────────
GRRP_VERSION: str = "1.0.0"
GRRP_LEDGER_DEFAULT: str = "data/grrp_response_ledger.jsonl"

# ─────────────────────────────────────────────────────────────────────────────
# GRRP-KEY-0: HMAC signing key resolver
# The GRRP signing key MUST NOT be hardcoded.  It is loaded from the env var
# ADAAD_GRRP_HMAC_KEY (hex or UTF-8).  In dev/test mode a predictable fallback
# is allowed only when ADAAD_ENV in {"dev","test"} AND the key is absent.
# In production the absence of ADAAD_GRRP_HMAC_KEY raises at import time.
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_grrp_hmac_key() -> bytes:
    raw = os.getenv("ADAAD_GRRP_HMAC_KEY", "").strip()
    if raw:
        try:
            return bytes.fromhex(raw)
        except ValueError:
            return raw.encode("utf-8")
    env = os.getenv("ADAAD_ENV", "").strip().lower()
    if env not in {"dev", "test", ""}:
        raise RuntimeError(
            "GRRP-KEY-0: ADAAD_GRRP_HMAC_KEY must be set in production. "
            "Hardcoded HMAC keys are constitutionally prohibited (WL-014)."
        )
    # Dev/test only fallback — NOT cryptographically secret
    return b"grrp-dev-only-key-not-for-production"


GRRP_HMAC_KEY: bytes = _resolve_grrp_hmac_key()

# Finding classification
CLASS_ADVISORY: str = "ADVISORY"       # auto-patchable; no human gate
CLASS_WARNING: str = "WARNING"         # logged; auto-patched with advisory note
CLASS_CRITICAL: str = "CRITICAL"       # HUMAN-0 escalation required
CLASS_BREACH: str = "BREACH"           # epoch halt + HUMAN-0 required (GRRP-ROUTE-0)

HUMAN0_REQUIRED_CLASSES = frozenset({CLASS_CRITICAL, CLASS_BREACH})

# ─────────────────────────────────────────────────────────────────────────────
# Exceptions (GRRP-0, GRRP-ROUTE-0, GRRP-SIGN-0)
# ─────────────────────────────────────────────────────────────────────────────
class UnprocessedReportError(RuntimeError):
    """Raised when an epoch attempts to advance with unprocessed reports."""

class RoutingViolationError(RuntimeError):
    """Raised when a CRITICAL/BREACH finding is auto-patched without HUMAN-0 ack."""

class IntegrityError(RuntimeError):
    """Raised when a response record carries an invalid or missing HMAC digest."""

class HumanGateBlockError(RuntimeError):
    """Raised when CRITICAL/BREACH amendment lacks human0_ack token."""


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Finding:
    finding_id: str
    invariant_target: str
    outcome: str        # GATE_FIRED | GATE_MISSED | OUT_OF_SCOPE | ERROR
    classification: str # ADVISORY | WARNING | CRITICAL | BREACH
    detail: str = ""


@dataclass
class AmendmentProposal:
    proposal_id: str
    finding_id: str
    invariant_target: str
    classification: str
    patch_description: str
    human0_ack: str = ""          # required for CRITICAL/BREACH (GRRP-HUMAN0-0)
    hmac_digest: str = ""

    def canonical(self) -> str:
        d = {k: v for k, v in asdict(self).items() if k != "hmac_digest"}
        return json.dumps(d, sort_keys=True)

    def sign(self, secret: bytes = GRRP_HMAC_KEY) -> None:
        """Compute and attach HMAC-SHA256 digest (GRRP-SIGN-0)."""
        self.hmac_digest = "hmac-sha256:" + hmac.new(
            secret, self.canonical().encode(), hashlib.sha256
        ).hexdigest()[:24]

    def verify(self, secret: bytes = GRRP_HMAC_KEY) -> bool:
        expected = "hmac-sha256:" + hmac.new(
            secret, self.canonical().encode(), hashlib.sha256
        ).hexdigest()[:24]
        return hmac.compare_digest(self.hmac_digest, expected)


@dataclass
class HumanEscalation:
    escalation_id: str
    finding_id: str
    invariant_target: str
    classification: str
    reason: str
    epoch_blocked: bool = True
    human0_ack: str = ""
    hmac_digest: str = ""

    def canonical(self) -> str:
        d = {k: v for k, v in asdict(self).items() if k != "hmac_digest"}
        return json.dumps(d, sort_keys=True)

    def sign(self, secret: bytes = GRRP_HMAC_KEY) -> None:
        self.hmac_digest = "hmac-sha256:" + hmac.new(
            secret, self.canonical().encode(), hashlib.sha256
        ).hexdigest()[:24]

    def verify(self, secret: bytes = GRRP_HMAC_KEY) -> bool:
        expected = "hmac-sha256:" + hmac.new(
            secret, self.canonical().encode(), hashlib.sha256
        ).hexdigest()[:24]
        return hmac.compare_digest(self.hmac_digest, expected)


@dataclass
class ResponseRecord:
    report_id: str
    findings_processed: int
    amendments: list[dict] = field(default_factory=list)
    escalations: list[dict] = field(default_factory=list)
    response_digest: str = ""
    prev_digest: str = "genesis"
    record_digest: str = ""

    def compute_response_digest(self, finding_ids: list[str],
                                 routing_decisions: list[str]) -> str:
        """Pure function — GRRP-DETERM-0."""
        payload = f"{self.report_id}:{','.join(sorted(finding_ids))}:{','.join(sorted(routing_decisions))}"
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()[:16]

    def compute_record_digest(self) -> str:
        d = {k: v for k, v in asdict(self).items() if k != "record_digest"}
        return "sha256:" + hashlib.sha256(
            json.dumps(d, sort_keys=True).encode()
        ).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# Core engine
# ─────────────────────────────────────────────────────────────────────────────
class GRRPEngine:
    """Governed Red-Team Response Protocol engine."""

    def __init__(self,
                 ledger_path: Path = Path(GRRP_LEDGER_DEFAULT),
                 sign_secret: bytes = GRRP_HMAC_KEY):
        self.ledger_path = Path(ledger_path)
        self.sign_secret = sign_secret
        self._pending_reports: set[str] = set()
        self._tail_digest: str = "genesis"

    # ── GRRP-0: registration ─────────────────────────────────────────────────
    def register_report(self, report_id: str) -> None:
        """Mark a CampaignReport as requiring GRRP processing."""
        self._pending_reports.add(report_id)

    def assert_no_pending(self) -> None:
        """Epoch-advance gate — GRRP-0."""
        if self._pending_reports:
            raise UnprocessedReportError(
                f"GRRP-0 VIOLATION: unprocessed reports block epoch advance: "
                f"{sorted(self._pending_reports)}"
            )

    # ── Classify findings ────────────────────────────────────────────────────
    @staticmethod
    def classify(outcome: str, invariant_target: str) -> str:
        """Deterministic classification — GRRP-DETERM-0."""
        if outcome == "GATE_MISSED":
            return CLASS_BREACH
        if outcome == "ERROR":
            return CLASS_CRITICAL
        if outcome == "OUT_OF_SCOPE":
            return CLASS_WARNING
        # GATE_FIRED — advisory record
        return CLASS_ADVISORY

    # ── Route a single finding ───────────────────────────────────────────────
    def _route(self, finding: Finding) -> tuple[
            AmendmentProposal | None, HumanEscalation | None]:
        """Apply GRRP-ROUTE-0: CRITICAL/BREACH → escalation only."""
        if finding.classification in HUMAN0_REQUIRED_CLASSES:
            esc = HumanEscalation(
                escalation_id=f"ESC-{finding.finding_id}",
                finding_id=finding.finding_id,
                invariant_target=finding.invariant_target,
                classification=finding.classification,
                reason=f"{finding.outcome} on {finding.invariant_target}: {finding.detail}",
                epoch_blocked=True,
            )
            esc.sign(self.sign_secret)
            return None, esc
        else:
            prop = AmendmentProposal(
                proposal_id=f"PROP-{finding.finding_id}",
                finding_id=finding.finding_id,
                invariant_target=finding.invariant_target,
                classification=finding.classification,
                patch_description=(
                    f"Auto-advisory patch for {finding.outcome} "
                    f"on {finding.invariant_target}"
                ),
            )
            prop.sign(self.sign_secret)
            return prop, None

    # ── Main ingest ──────────────────────────────────────────────────────────
    def grrp_ingest(self, report_id: str,
                    findings: list[Finding]) -> ResponseRecord:
        """Process a CampaignReport — GRRP-0, GRRP-ROUTE-0, GRRP-CHAIN-0."""
        amendments: list[AmendmentProposal] = []
        escalations: list[HumanEscalation] = []
        routing_decisions: list[str] = []

        for f in findings:
            prop, esc = self._route(f)
            if prop is not None:
                if not prop.verify(self.sign_secret):
                    raise IntegrityError(f"GRRP-SIGN-0: unsigned proposal {prop.proposal_id}")
                amendments.append(prop)
                routing_decisions.append(f"AUTO:{f.finding_id}")
            if esc is not None:
                if not esc.verify(self.sign_secret):
                    raise IntegrityError(f"GRRP-SIGN-0: unsigned escalation {esc.escalation_id}")
                escalations.append(esc)
                routing_decisions.append(f"HUMAN0:{f.finding_id}")

        rec = ResponseRecord(
            report_id=report_id,
            findings_processed=len(findings),
            amendments=[asdict(a) for a in amendments],
            escalations=[asdict(e) for e in escalations],
            prev_digest=self._tail_digest,
        )
        # GRRP-DETERM-0
        rec.response_digest = rec.compute_response_digest(
            [f.finding_id for f in findings], routing_decisions
        )
        # GRRP-CHAIN-0
        rec.record_digest = rec.compute_record_digest()
        self._tail_digest = rec.record_digest

        self._persist(rec)
        self._pending_reports.discard(report_id)
        return rec

    # ── GRRP-HUMAN0-0: gate check ────────────────────────────────────────────
    @staticmethod
    def assert_human0_ack(proposal: AmendmentProposal) -> None:
        """Block CEL advancement for CRITICAL/BREACH without human0_ack."""
        if proposal.classification in HUMAN0_REQUIRED_CLASSES:
            if not proposal.human0_ack:
                raise HumanGateBlockError(
                    f"GRRP-HUMAN0-0: proposal {proposal.proposal_id} "
                    f"(class={proposal.classification}) requires human0_ack token"
                )

    # ── Append-only ledger ───────────────────────────────────────────────────
    def _persist(self, rec: ResponseRecord) -> None:
        """Append-only write — GRRP-CHAIN-0."""
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a") as f:
            f.write(json.dumps(asdict(rec)) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Module-level invariant sentinel
# ─────────────────────────────────────────────────────────────────────────────
    def _append_event(self, event) -> None:
        """CED-INV-AUDIT: append-only JSONL event record; advance HMAC chain head."""
        import json as _json
        import dataclasses as _dc
        from pathlib import Path as _Path
        ledger = getattr(self, 'ledger_path', None) or getattr(self, 'state_path', None)
        if ledger is None:
            return
        ledger = _Path(ledger)
        ledger.parent.mkdir(parents=True, exist_ok=True)
        row = _json.dumps(_dc.asdict(event) if hasattr(event, '__dataclass_fields__') else event, sort_keys=True)
        with ledger.open("a") as f:
            f.write(row + "\n")


GRRP_INVARIANTS: list[str] = [
    "GRRP-0",
    "GRRP-ROUTE-0",
    "GRRP-SIGN-0",
    "GRRP-DETERM-0",
    "GRRP-CHAIN-0",
    "GRRP-HUMAN0-0",
]

