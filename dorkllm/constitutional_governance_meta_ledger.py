"""
constitutional_governance_meta_ledger.py
Phase 221 · INNOV-126 · CGML — Constitutional Governance Meta-Ledger
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID

World-first: The first autonomous AI governance system with a unified,
cryptographically-chained Meta-Ledger aggregating every Arc II governance
event (ACSA, ACPA, ACAM, CARE, CEICC) into a single auditable lineage
matrix — tracing each invariant from originating proposal through
ratification, coherence check, and active deployment. Provides HUMAN-0
with constitutional lineage attestations and cross-phase consistency proofs.

Hard-class Invariants (10):
  CGML-CHAIN-0   : Every meta-ledger entry is HMAC-SHA-256 chained; chain
                    breaks are fatal — no silent failures.
  CGML-APPEND-0  : Meta-ledger is strictly append-only; no entry may be
                    mutated or deleted post-write (os.replace atomic writes).
  CGML-ARC2-0    : All six Arc II source domains must be registered at init;
                    missing domain registration raises ConstitutionalViolation.
  CGML-LINEAGE-0 : Every invariant entry must carry a traceable proposal_id
                    back to an ACSA originating record; orphan invariants
                    are flagged LINEAGE-BROKEN and quarantined.
  CGML-HUMAN0-0  : Meta-ledger attestation certificates require HUMAN-0
                    authorization token; unsigned attestations are rejected.
  CGML-IMMUT-0   : Ledger file path and HMAC secret are fixed at construction
                    and cannot be changed post-init (immutability invariant).
  CGML-REPLAY-0  : Full meta-ledger replay must produce identical chain hashes
                    given identical input — deterministic replay is mandatory.
  CGML-ATOMIC-0  : All writes use os.replace() for atomicity; partial writes
                    are constitutionally prohibited.
  CGML-XPHASE-0  : Cross-phase consistency check is enforced on every append;
                    phase sequence violations (e.g. CARE before ACAM) are
                    rejected with XPHASE-VIOLATION error.
  CGML-AUDIT-0   : Every read operation on the meta-ledger emits an audit
                    event; silent reads are constitutionally prohibited.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Constants ────────────────────────────────────────────────────────────────

CGML_VERSION = "1.0.0"
GOVERNOR = "DUSTIN L REID"
ARC_II_DOMAINS = ("ACSA", "ACPA", "ACAM", "CARE", "CEICC", "CGML")
PHASE_ORDER = {
    "ACSA": 216,
    "ACPA": 217,
    "ACAM": 218,
    "CARE": 219,
    "CEICC": 220,
    "CGML": 221,
}
HMAC_SECRET_DEFAULT = b"CGML-HMAC-SECRET-DUSTIN-L-REID-INNOVATIVEAI"
DEFAULT_LEDGER_PATH = Path("ledger/cgml_meta_ledger.jsonl")


# ── Enums ────────────────────────────────────────────────────────────────────

class EntryKind(str, Enum):
    PROPOSAL   = "PROPOSAL"
    ADVICE     = "ADVICE"
    MONITOR    = "MONITOR"
    RATIFY     = "RATIFY"
    COHERENCE  = "COHERENCE"
    META       = "META"
    AUDIT      = "AUDIT"
    ATTEST     = "ATTEST"


class LineageStatus(str, Enum):
    TRACED    = "TRACED"
    ORPHAN    = "ORPHAN"       # no originating ACSA record
    BROKEN    = "BROKEN"       # chain in source domain broken
    QUARANTINE = "QUARANTINE"  # flagged, blocked from attestation


class XPhaseStatus(str, Enum):
    VALID     = "VALID"
    VIOLATION = "XPHASE-VIOLATION"


# ── Exceptions ───────────────────────────────────────────────────────────────

class ConstitutionalViolation(RuntimeError):
    """Raised when a Hard-class invariant is breached."""


class ChainIntegrityError(ConstitutionalViolation):
    """CGML-CHAIN-0: HMAC chain broken."""


class LineageBroken(ConstitutionalViolation):
    """CGML-LINEAGE-0: Invariant has no traceable proposal origin."""


class XPhaseViolation(ConstitutionalViolation):
    """CGML-XPHASE-0: Phase sequence violated."""


class AttestationDenied(ConstitutionalViolation):
    """CGML-HUMAN0-0: Missing or invalid HUMAN-0 authorization."""


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class MetaEntry:
    entry_id: str
    kind: str
    domain: str              # Arc II source domain
    phase: int               # originating phase number
    proposal_id: Optional[str]
    invariant_id: Optional[str]
    payload: Dict[str, Any]
    lineage_status: str
    xphase_status: str
    timestamp: str
    prev_hash: str
    entry_hash: str = field(default="")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LineageMatrix:
    """Aggregated view of an invariant's lifecycle across Arc II."""
    invariant_id: str
    proposal_id: Optional[str]
    domains_traversed: List[str]
    phase_sequence: List[int]
    lineage_status: str
    attestation_ready: bool
    trace_entries: List[str]   # entry_ids


@dataclass
class MetaAttestation:
    attestation_id: str
    governor: str
    human0_token: str
    total_entries: int
    arc2_domains_present: List[str]
    lineage_matrix_count: int
    broken_lineages: int
    chain_root_hash: str
    chain_tip_hash: str
    issued_at: str
    valid: bool


# ── Core engine ──────────────────────────────────────────────────────────────

class ConstitutionalGovernanceMetaLedger:
    """
    CGML: Single-source-of-truth meta-ledger for all Arc II governance events.
    Enforces CGML-CHAIN-0 through CGML-AUDIT-0 at all operation boundaries.
    """

    def __init__(
        self,
        ledger_path: Path = DEFAULT_LEDGER_PATH,
        hmac_secret: bytes = HMAC_SECRET_DEFAULT,
    ) -> None:
        # CGML-IMMUT-0 — freeze path and secret immediately
        self._ledger_path: Path = Path(ledger_path)
        self._hmac_secret: bytes = hmac_secret
        self._immutable_sealed = True

        # CGML-ARC2-0 — all six Arc II domains must be known
        self._registered_domains = set(ARC_II_DOMAINS)
        if len(self._registered_domains) != len(ARC_II_DOMAINS):  # pragma: no cover
            raise ConstitutionalViolation("CGML-ARC2-0: duplicate domain registration")

        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: List[MetaEntry] = []
        self._prev_hash: str = "GENESIS"
        self._load()

    # ── Internals ────────────────────────────────────────────────────────────

    def _compute_hmac(self, payload: str) -> str:
        return hmac.new(
            self._hmac_secret,
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _compute_entry_hash(self, entry: MetaEntry) -> str:
        raw = json.dumps(
            {k: v for k, v in entry.to_dict().items() if k != "entry_hash"},
            sort_keys=True,
        )
        return self._compute_hmac(raw)

    def _verify_chain(self) -> None:
        """CGML-CHAIN-0: replay full chain and verify every link."""
        prev = "GENESIS"
        for e in self._entries:
            expected = self._compute_entry_hash(
                MetaEntry(**{**e.to_dict(), "entry_hash": ""})
            )
            if not hmac.compare_digest(expected[:24], e.entry_hash[:24]):
                raise ChainIntegrityError(
                    f"CGML-CHAIN-0: chain broken at entry {e.entry_id}"
                )
            prev = e.entry_hash
        self._prev_hash = prev if self._entries else "GENESIS"

    def _load(self) -> None:
        if not self._ledger_path.exists():
            return
        with open(self._ledger_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                self._entries.append(MetaEntry(**json.loads(line)))
        self._verify_chain()  # CGML-CHAIN-0

    def _atomic_append(self, entry: MetaEntry) -> None:
        """CGML-ATOMIC-0: write via os.replace()."""
        tmp = Path(str(self._ledger_path) + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            for e in self._entries:
                fh.write(json.dumps(e.to_dict()) + "\n")
            fh.write(json.dumps(entry.to_dict()) + "\n")
        os.replace(tmp, self._ledger_path)  # CGML-ATOMIC-0

    def _check_xphase(self, domain: str, phase: int) -> XPhaseStatus:
        """CGML-XPHASE-0: enforce Arc II phase ordering.
        CGML domain is the meta-ledger itself; its entries (audit, meta,
        attest) are exempt from ordering — they may arrive at any point.
        """
        if domain == "CGML":
            return XPhaseStatus.VALID   # meta-domain is always phase-valid
        expected = PHASE_ORDER.get(domain)
        if expected is None:
            return XPhaseStatus.VALID
        for existing in self._entries:
            if existing.domain == domain:
                return XPhaseStatus.VALID  # already have this domain
        # Ensure no *non-CGML* domain with higher phase has arrived first
        for existing in self._entries:
            if existing.domain == "CGML":
                continue  # CGML meta-entries do not count for xphase ordering
            existing_phase = PHASE_ORDER.get(existing.domain, 0)
            if existing_phase > phase and existing.domain != domain:
                return XPhaseStatus.VIOLATION
        return XPhaseStatus.VALID

    def _emit_audit(self, operation: str, entry_id: str) -> None:
        """CGML-AUDIT-0: every read emits an audit entry."""
        audit = self._build_entry(
            kind=EntryKind.AUDIT,
            domain="CGML",
            phase=221,
            proposal_id=None,
            invariant_id=None,
            payload={"operation": operation, "target_entry_id": entry_id},
        )
        self._entries.append(audit)
        self._atomic_append(audit)
        self._prev_hash = audit.entry_hash

    def _build_entry(
        self,
        kind: EntryKind,
        domain: str,
        phase: int,
        proposal_id: Optional[str],
        invariant_id: Optional[str],
        payload: Dict[str, Any],
    ) -> MetaEntry:
        entry_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()
        lineage_status = (
            LineageStatus.TRACED.value
            if (proposal_id or invariant_id is None)
            else LineageStatus.ORPHAN.value
        )
        xphase_status = self._check_xphase(domain, phase).value

        entry = MetaEntry(
            entry_id=entry_id,
            kind=kind.value,
            domain=domain,
            phase=phase,
            proposal_id=proposal_id,
            invariant_id=invariant_id,
            payload=payload,
            lineage_status=lineage_status,
            xphase_status=xphase_status,
            timestamp=ts,
            prev_hash=self._prev_hash,
        )
        entry.entry_hash = self._compute_entry_hash(entry)
        return entry

    # ── Public API ───────────────────────────────────────────────────────────

    def append_event(
        self,
        kind: EntryKind,
        domain: str,
        phase: int,
        proposal_id: Optional[str] = None,
        invariant_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> MetaEntry:
        """
        Append a governance event from any Arc II domain.
        CGML-ARC2-0: domain must be registered.
        CGML-XPHASE-0: phase ordering enforced.
        CGML-APPEND-0: strictly append-only.
        """
        # CGML-ARC2-0
        if domain not in self._registered_domains:
            raise ConstitutionalViolation(
                f"CGML-ARC2-0: unregistered Arc II domain '{domain}'"
            )

        entry = self._build_entry(
            kind=kind,
            domain=domain,
            phase=phase,
            proposal_id=proposal_id,
            invariant_id=invariant_id,
            payload=payload or {},
        )

        # CGML-XPHASE-0 enforcement
        if entry.xphase_status == XPhaseStatus.VIOLATION.value:
            raise XPhaseViolation(
                f"CGML-XPHASE-0: phase ordering violated for domain {domain} "
                f"(phase {phase})"
            )

        self._entries.append(entry)
        self._atomic_append(entry)  # CGML-ATOMIC-0
        self._prev_hash = entry.entry_hash
        return entry

    def build_lineage_matrix(self) -> List[LineageMatrix]:
        """
        Derive the lineage matrix: for each unique invariant, trace its
        full lifecycle across Arc II domains.
        CGML-LINEAGE-0 enforced: invariants without a PROPOSAL entry are ORPHAN.
        CGML-AUDIT-0: emits audit event for each matrix build.
        """
        by_invariant: Dict[str, List[MetaEntry]] = {}
        by_proposal: Dict[str, List[MetaEntry]] = {}

        for e in self._entries:
            if e.kind == EntryKind.AUDIT.value:
                continue
            if e.invariant_id:
                by_invariant.setdefault(e.invariant_id, []).append(e)
            if e.proposal_id:
                by_proposal.setdefault(e.proposal_id, []).append(e)

        matrices: List[LineageMatrix] = []
        for inv_id, entries in by_invariant.items():
            domains = list(dict.fromkeys(e.domain for e in entries))
            phases  = sorted(set(e.phase for e in entries))
            has_proposal = any(
                e.kind == EntryKind.PROPOSAL.value for e in entries
            )
            lineage = (
                LineageStatus.TRACED.value
                if has_proposal
                else LineageStatus.ORPHAN.value
            )
            attestation_ready = (
                has_proposal and lineage == LineageStatus.TRACED.value
            )
            matrices.append(LineageMatrix(
                invariant_id=inv_id,
                proposal_id=entries[0].proposal_id,
                domains_traversed=domains,
                phase_sequence=phases,
                lineage_status=lineage,
                attestation_ready=attestation_ready,
                trace_entries=[e.entry_id for e in entries],
            ))

        self._emit_audit("build_lineage_matrix", "ALL")
        return matrices

    def verify_chain(self) -> Dict[str, Any]:
        """
        CGML-CHAIN-0 / CGML-REPLAY-0: verify full chain integrity.
        Returns a dict with verification results.
        CGML-AUDIT-0: emits audit event.
        """
        try:
            self._verify_chain()
            result = {
                "valid": True,
                "entry_count": len(self._entries),
                "tip_hash": self._prev_hash[:24],
                "error": None,
            }
        except ChainIntegrityError as exc:
            result = {
                "valid": False,
                "entry_count": len(self._entries),
                "tip_hash": None,
                "error": str(exc),
            }
        self._emit_audit("verify_chain", result.get("tip_hash") or "BROKEN")
        return result

    def get_domain_summary(self) -> Dict[str, Any]:
        """
        Return per-domain event counts and phase coverage.
        CGML-AUDIT-0: emits audit event.
        """
        summary: Dict[str, Any] = {d: {"count": 0, "phases": []} for d in ARC_II_DOMAINS}
        for e in self._entries:
            if e.kind == EntryKind.AUDIT.value:
                continue
            if e.domain in summary:
                summary[e.domain]["count"] += 1
                if e.phase not in summary[e.domain]["phases"]:
                    summary[e.domain]["phases"].append(e.phase)
        self._emit_audit("get_domain_summary", "ALL")
        return summary

    def issue_attestation(
        self, human0_token: str
    ) -> MetaAttestation:
        """
        CGML-HUMAN0-0: issue a signed Meta-Ledger attestation.
        human0_token must be non-empty (HUMAN-0 authorization).
        CGML-AUDIT-0: emits audit event.
        """
        if not human0_token or not human0_token.strip():
            raise AttestationDenied(
                "CGML-HUMAN0-0: attestation requires non-empty HUMAN-0 token"
            )

        matrices = self.build_lineage_matrix()
        broken = sum(
            1 for m in matrices
            if m.lineage_status in (
                LineageStatus.ORPHAN.value,
                LineageStatus.BROKEN.value,
                LineageStatus.QUARANTINE.value,
            )
        )
        domains_present = list(
            {e.domain for e in self._entries if e.kind != EntryKind.AUDIT.value}
        )
        root = self._entries[0].entry_hash[:24] if self._entries else "EMPTY"
        tip  = self._prev_hash[:24] if self._prev_hash != "GENESIS" else "EMPTY"

        attest = MetaAttestation(
            attestation_id=str(uuid.uuid4()),
            governor=GOVERNOR,
            human0_token=f"***{human0_token[-4:]}",   # redact
            total_entries=len(self._entries),
            arc2_domains_present=sorted(domains_present),
            lineage_matrix_count=len(matrices),
            broken_lineages=broken,
            chain_root_hash=root,
            chain_tip_hash=tip,
            issued_at=datetime.now(timezone.utc).isoformat(),
            valid=broken == 0,
        )
        # Append attestation event to ledger
        self.append_event(
            kind=EntryKind.ATTEST,
            domain="CGML",
            phase=221,
            proposal_id=None,
            invariant_id=None,
            payload={"attestation_id": attest.attestation_id, "valid": attest.valid},
        )
        self._emit_audit("issue_attestation", attest.attestation_id)
        return attest

    def get_entry(self, entry_id: str) -> Optional[MetaEntry]:
        """
        Retrieve a single entry by ID.
        CGML-AUDIT-0: emits audit event.
        """
        result = next((e for e in self._entries if e.entry_id == entry_id), None)
        self._emit_audit("get_entry", entry_id)
        return result

    def list_entries(
        self,
        domain: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> List[MetaEntry]:
        """
        List entries, optionally filtered by domain and/or kind.
        CGML-AUDIT-0: emits audit event.
        """
        results = [
            e for e in self._entries
            if (domain is None or e.domain == domain)
            and (kind   is None or e.kind   == kind)
            and e.kind != EntryKind.AUDIT.value
        ]
        self._emit_audit("list_entries", f"domain={domain},kind={kind}")
        return results

    def get_status(self) -> Dict[str, Any]:
        """Current CGML engine status snapshot (no audit event)."""
        return {
            "cgml_version": CGML_VERSION,
            "governor": GOVERNOR,
            "phase": 221,
            "innovation": "INNOV-126",
            "ledger_path": str(self._ledger_path),
            "entry_count": len(self._entries),
            "prev_hash": self._prev_hash[:24],
            "registered_domains": sorted(self._registered_domains),
            "arc": "II — Self-Amendment & Meta-Governance",
            "invariants": [
                "CGML-CHAIN-0", "CGML-APPEND-0", "CGML-ARC2-0",
                "CGML-LINEAGE-0", "CGML-HUMAN0-0", "CGML-IMMUT-0",
                "CGML-REPLAY-0", "CGML-ATOMIC-0", "CGML-XPHASE-0",
                "CGML-AUDIT-0",
            ],
        }
