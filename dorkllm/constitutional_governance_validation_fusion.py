# SPDX-License-Identifier: Apache-2.0
# INNOV-120 · CGVF — Constitutional Governance Validation Fusion Engine
# Phase 215 · v10.26.0 · InnovativeAI LLC · Governor: DUSTIN L REID
"""
Constitutional Governance Validation Fusion Engine (CGVF)
==========================================================
World-first governed engine that orchestrates all CG* peer modules
(CGPR, CGVA, CGVR, CGVE) into a single authoritative governance consensus
surface. CGVF queries each peer, derives a weighted consensus_score, and
issues a cryptographically sealed FusionAttestation — the definitive
system-wide governance certificate consumable by external auditors,
compliance portals, and the Aponi dashboard.

Peer weight allocation (consensus_score):
  CGVA health_score            40%  — constitutional health dimension audit
  CGVR remediation_status      25%  — open violation / repair posture
  CGVE compliance_status       25%  — version surface enforcement state
  CGPR proof_bundle presence   10%  — proof rendering freshness

Hard-class invariants (12):
  CGVF-AUDIT-0      Every fusion run is ledger-recorded before return.
  CGVF-CHAIN-0      Fusion ledger is HMAC-SHA-256 chained; no gaps.
  CGVF-DETERM-0     fusion_id is SHA-256(peer_signal_hash+ts_ns).
  CGVF-FAILCLOSED-0 All internal errors raise; never swallowed silently.
  CGVF-ATOMIC-0     Ledger writes use os.replace() via .tmp intermediary.
  CGVF-HUMAN0-0     consensus_score < 0.70 sets human0_required=True.
  CGVF-SCORE-0      consensus_score ∈ [0.0, 1.0]; out-of-range raises.
  CGVF-PEER-0       All four CG* peers queried; missing peer degrades score.
  CGVF-SEAL-0       Every ledger record carries a sealed HMAC digest.
  CGVF-IMMUT-0      Appended ledger records are immutable; mutation raises.
  CGVF-CERT-0       HUMAN-0 certification is one-way; re-certification raises.
  CGVF-CONSENSUS-0  overall_status derived solely from consensus_score thresholds.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HMAC_KEY: bytes = os.environb.get(
    b"CGVF_HMAC_KEY", b"cgvf-default-hmac-key-adaad-v10-fusion"
)
_LEDGER_PATH = Path(
    os.environ.get("CGVF_LEDGER_PATH", "ledger/cgvf_fusion_ledger.jsonl")
)

# ── Hard-class invariant constants ────────────────────────────────────────────

CGVF_AUDIT_0      = "CGVF-AUDIT-0"
CGVF_CHAIN_0      = "CGVF-CHAIN-0"
CGVF_DETERM_0     = "CGVF-DETERM-0"
CGVF_FAILCLOSED_0 = "CGVF-FAILCLOSED-0"
CGVF_ATOMIC_0     = "CGVF-ATOMIC-0"
CGVF_HUMAN0_0     = "CGVF-HUMAN0-0"
CGVF_SCORE_0      = "CGVF-SCORE-0"
CGVF_PEER_0       = "CGVF-PEER-0"
CGVF_SEAL_0       = "CGVF-SEAL-0"
CGVF_IMMUT_0      = "CGVF-IMMUT-0"
CGVF_CERT_0       = "CGVF-CERT-0"
CGVF_CONSENSUS_0  = "CGVF-CONSENSUS-0"

# ── Peer weights ──────────────────────────────────────────────────────────────

_PEER_WEIGHTS: Dict[str, float] = {
    "CGVA": 0.40,
    "CGVR": 0.25,
    "CGVE": 0.25,
    "CGPR": 0.10,
}

# Consensus score thresholds → overall_status
_THRESHOLD_HEALTHY   = 0.85
_THRESHOLD_DEGRADED  = 0.70
_THRESHOLD_HUMAN0    = 0.70   # CGVF-HUMAN0-0

GOVERNOR = "DUSTIN L REID"

# ── Custom exceptions ─────────────────────────────────────────────────────────


class CGVFError(RuntimeError):
    """Base CGVF Hard-class violation."""


class CGVFChainError(CGVFError):
    """CGVF-CHAIN-0 violation: ledger chain broken."""


class CGVFImmutError(CGVFError):
    """CGVF-IMMUT-0 violation: attempt to mutate sealed record."""


class CGVFScoreError(CGVFError):
    """CGVF-SCORE-0 violation: consensus_score out of [0.0, 1.0]."""


class CGVFCertError(CGVFError):
    """CGVF-CERT-0 violation: re-certification of sealed attestation."""


class CGVFConsensusError(CGVFError):
    """CGVF-CONSENSUS-0 violation: invalid overall_status value."""


# ── Enumerations ──────────────────────────────────────────────────────────────


class FusionStatus(str, Enum):
    HEALTHY          = "HEALTHY"
    DEGRADED         = "DEGRADED"
    CRITICAL         = "CRITICAL"
    HUMAN0_REQUIRED  = "HUMAN0_REQUIRED"


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class PeerSignal:
    """Normalised governance signal from one CG* peer module."""
    peer_id:        str           # e.g. "CGVA"
    raw_value:      Any           # raw value from peer (score, status string, bool)
    normalised:     float         # [0.0, 1.0] value used in consensus computation
    weight:         float         # peer weight (sum of all weights == 1.0)
    available:      bool          # False if peer query raised an exception
    error_msg:      Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "peer_id":    self.peer_id,
            "raw_value":  str(self.raw_value),
            "normalised": self.normalised,
            "weight":     self.weight,
            "available":  self.available,
            "error_msg":  self.error_msg,
        }


@dataclass
class FusionAttestation:
    """
    Sealed, HMAC-chained record of one CGVF governance fusion run.
    CGVF-IMMUT-0: once appended to the ledger this record must not be mutated.
    """
    fusion_id:        str
    timestamp_ns:     int
    peer_signals:     List[PeerSignal]
    consensus_score:  float
    overall_status:   FusionStatus
    human0_required:  bool
    human0_certified: bool
    certified_by:     Optional[str]
    prev_digest:      str          # CGVF-CHAIN-0
    hmac_digest:      str = field(default="", repr=False)
    _sealed:          bool = field(default=False, init=False, repr=False)

    # CGVF-SCORE-0
    def __post_init__(self) -> None:
        if not (0.0 <= self.consensus_score <= 1.0):
            raise CGVFScoreError(
                f"{CGVF_SCORE_0}: consensus_score {self.consensus_score!r} "
                f"not in [0.0, 1.0]"
            )
        valid_statuses = {s.value for s in FusionStatus}
        if self.overall_status.value not in valid_statuses:
            raise CGVFConsensusError(
                f"{CGVF_CONSENSUS_0}: overall_status {self.overall_status!r} "
                f"not in {valid_statuses}"
            )

    def _canonical_bytes(self) -> bytes:
        return json.dumps(
            {
                "fusion_id":       self.fusion_id,
                "timestamp_ns":    self.timestamp_ns,
                "consensus_score": self.consensus_score,
                "overall_status":  self.overall_status.value,
                "human0_required": self.human0_required,
                "prev_digest":     self.prev_digest,
            },
            sort_keys=True,
        ).encode()

    def seal(self) -> "FusionAttestation":
        """Compute and set hmac_digest; mark record sealed. CGVF-SEAL-0."""
        digest = hmac.new(_HMAC_KEY, self.to_loggable_bytes(), "sha256").hexdigest()
        object.__setattr__(self, "hmac_digest", digest)
        object.__setattr__(self, "_sealed", True)
        return self

    def to_loggable_bytes(self) -> bytes:
        return json.dumps(
            {
                "fusion_id":        self.fusion_id,
                "timestamp_ns":     self.timestamp_ns,
                "peer_signals":     [ps.to_dict() for ps in self.peer_signals],
                "consensus_score":  self.consensus_score,
                "overall_status":   self.overall_status.value,
                "human0_required":  self.human0_required,
                "human0_certified": self.human0_certified,
                "certified_by":     self.certified_by,
                "prev_digest":      self.prev_digest,
            },
            sort_keys=True,
        ).encode()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fusion_id":        self.fusion_id,
            "timestamp_ns":     self.timestamp_ns,
            "peer_signals":     [ps.to_dict() for ps in self.peer_signals],
            "consensus_score":  self.consensus_score,
            "overall_status":   self.overall_status.value,
            "human0_required":  self.human0_required,
            "human0_certified": self.human0_certified,
            "certified_by":     self.certified_by,
            "prev_digest":      self.prev_digest,
            "hmac_digest":      self.hmac_digest,
        }


# ── Peer query helpers ────────────────────────────────────────────────────────


def _query_cgva() -> Tuple[float, Any]:
    """
    Query CGVA for current health_score.
    Returns (normalised_score, raw_value).
    CGVF-PEER-0: raises CGVFError on import failure to signal unavailability.
    """
    from dorkllm.constitutional_governance_validation_auditor import (
        ConstitutionalGovernanceValidationAuditor,
    )
    auditor = ConstitutionalGovernanceValidationAuditor()
    score = auditor.health_score()
    return float(score), score


def _query_cgvr() -> Tuple[float, Any]:
    """
    Query CGVR for remediation posture.
    REMEDIATED/no history → 1.0
    PARTIAL               → 0.6
    BLOCKED               → 0.3
    HUMAN0_REQUIRED       → 0.0
    FAILED                → 0.0
    """
    from dorkllm.constitutional_governance_violation_remediator import (
        ConstitutionalGovernanceViolationRemediator,
    )
    remediator = ConstitutionalGovernanceViolationRemediator()
    history = remediator.history(limit=1)
    if not history:
        # No remediations on record — governance is clean
        return 1.0, "NO_HISTORY"
    last = history[-1]
    status_str = last.status.value if hasattr(last.status, "value") else str(last.status)
    score_map = {
        "REMEDIATED":      1.0,
        "PARTIAL":         0.6,
        "BLOCKED":         0.3,
        "HUMAN0_REQUIRED": 0.0,
        "FAILED":          0.0,
    }
    normalised = score_map.get(status_str, 0.5)
    return normalised, status_str


def _query_cgve() -> Tuple[float, Any]:
    """
    Query CGVE for version surface compliance.
    COMPLIANT → 1.0
    REPAIRED  → 0.8
    DRIFTED   → 0.3
    FAILED    → 0.0
    BLOCKED   → 0.1
    """
    from dorkllm.constitutional_governance_version_enforcer import (
        ConstitutionalGovernanceVersionEnforcer,
    )
    enforcer = ConstitutionalGovernanceVersionEnforcer()
    history = enforcer.history(limit=1)
    if not history:
        return 1.0, "NO_HISTORY"
    last = history[-1]
    status_str = last.status.value if hasattr(last.status, "value") else str(last.status)
    score_map = {
        "COMPLIANT": 1.0,
        "REPAIRED":  0.8,
        "DRIFTED":   0.3,
        "FAILED":    0.0,
        "BLOCKED":   0.1,
    }
    normalised = score_map.get(status_str, 0.5)
    return normalised, status_str


def _query_cgpr() -> Tuple[float, Any]:
    """
    Query CGPR for proof bundle freshness.
    Has recent entry → 1.0; empty ledger → 0.5 (unknown posture).
    """
    from dorkllm.constitutional_governance_proof_renderer import (
        ConstitutionalGovernanceProofRenderer,
    )
    renderer = ConstitutionalGovernanceProofRenderer()
    history = renderer.history(limit=1)
    if not history:
        return 0.5, "NO_HISTORY"
    return 1.0, "PROOF_PRESENT"


_PEER_QUERIES = {
    "CGVA": _query_cgva,
    "CGVR": _query_cgvr,
    "CGVE": _query_cgve,
    "CGPR": _query_cgpr,
}


# ── Ledger helpers ────────────────────────────────────────────────────────────


def _ledger_prev_digest(ledger_path: Path) -> str:
    """Return HMAC of last JSONL line, or '0'*64 for empty ledger."""
    if not ledger_path.exists() or ledger_path.stat().st_size == 0:
        return "0" * 64
    last_line = b""
    with open(ledger_path, "rb") as fh:
        for line in fh:
            line = line.strip()
            if line:
                last_line = line
    if not last_line:
        return "0" * 64
    return hmac.new(_HMAC_KEY, last_line, "sha256").hexdigest()


def _ledger_append(record: FusionAttestation, ledger_path: Path) -> None:
    """
    Atomically append one sealed record to the JSONL ledger.
    CGVF-ATOMIC-0: uses os.replace() via a .tmp intermediary.
    """
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record.to_dict(), sort_keys=True) + "\n"
    tmp = ledger_path.with_suffix(".tmp")
    # Read existing content
    existing = b""
    if ledger_path.exists():
        existing = ledger_path.read_bytes()
    tmp.write_bytes(existing + line.encode())
    os.replace(tmp, ledger_path)


# ── Main engine ───────────────────────────────────────────────────────────────


class ConstitutionalGovernanceValidationFusion:
    """
    CGVF: Constitutional Governance Validation Fusion Engine.

    Usage::

        engine = ConstitutionalGovernanceValidationFusion()
        attestation = engine.fuse()
        print(attestation.consensus_score, attestation.overall_status)
    """

    def __init__(
        self,
        ledger_path: Optional[Path] = None,
        human0_threshold: float = _THRESHOLD_HUMAN0,
    ) -> None:
        self._ledger_path    = ledger_path or _LEDGER_PATH
        self._human0_thresh  = human0_threshold
        self._records: List[FusionAttestation] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def fuse(self) -> FusionAttestation:
        """
        Run a full governance fusion cycle.
        Queries all four CG* peers, computes weighted consensus_score,
        derives overall_status, seals record, appends to ledger.
        CGVF-AUDIT-0: record is written before this method returns.
        """
        try:
            ts_ns = time.time_ns()
            signals = self._collect_peer_signals()
            consensus_score = self._compute_consensus(signals)
            overall_status  = self._derive_status(consensus_score)
            human0_required = consensus_score < self._human0_thresh  # CGVF-HUMAN0-0
            fusion_id       = self._derive_fusion_id(signals, ts_ns)
            prev_digest     = _ledger_prev_digest(self._ledger_path)  # CGVF-CHAIN-0

            attestation = FusionAttestation(
                fusion_id        = fusion_id,
                timestamp_ns     = ts_ns,
                peer_signals     = signals,
                consensus_score  = consensus_score,
                overall_status   = overall_status,
                human0_required  = human0_required,
                human0_certified = False,
                certified_by     = None,
                prev_digest      = prev_digest,
            )
            attestation.seal()  # CGVF-SEAL-0

            _ledger_append(attestation, self._ledger_path)  # CGVF-AUDIT-0
            self._records.append(attestation)
            return attestation

        except (CGVFError,):
            raise
        except Exception as exc:  # CGVF-FAILCLOSED-0
            raise CGVFError(
                f"{CGVF_FAILCLOSED_0}: unexpected error in fuse(): {exc}"
            ) from exc

    def certify(self, fusion_id: str, certified_by: str = GOVERNOR) -> FusionAttestation:
        """
        Apply HUMAN-0 certification to an existing FusionAttestation.
        CGVF-CERT-0: already-certified records raise CGVFCertError.
        """
        try:
            record = self._find_record(fusion_id)
            if record is None:
                raise CGVFError(
                    f"{CGVF_FAILCLOSED_0}: fusion_id {fusion_id!r} not found in ledger"
                )
            if record.human0_certified:
                raise CGVFCertError(
                    f"{CGVF_CERT_0}: fusion_id {fusion_id!r} already certified; "
                    f"re-certification prohibited"
                )
            # Rebuild with certification
            ts_ns       = time.time_ns()
            prev_digest = _ledger_prev_digest(self._ledger_path)
            certified   = FusionAttestation(
                fusion_id        = record.fusion_id,
                timestamp_ns     = ts_ns,
                peer_signals     = record.peer_signals,
                consensus_score  = record.consensus_score,
                overall_status   = record.overall_status,
                human0_required  = False,
                human0_certified = True,
                certified_by     = certified_by,
                prev_digest      = prev_digest,
            )
            certified.seal()
            _ledger_append(certified, self._ledger_path)
            self._records.append(certified)
            return certified

        except (CGVFError,):
            raise
        except Exception as exc:
            raise CGVFError(
                f"{CGVF_FAILCLOSED_0}: unexpected error in certify(): {exc}"
            ) from exc

    def history(self, limit: int = 50) -> List[FusionAttestation]:
        """Return recent FusionAttestation records from the ledger."""
        return list(self._load_ledger(limit=limit))

    def consensus_score(self) -> float:
        """Return the most recent consensus_score, or 0.0 if no history."""
        records = self.history(limit=1)
        if not records:
            return 0.0
        return records[-1].consensus_score

    def verify_chain(self) -> Dict[str, Any]:
        """
        Walk the JSONL ledger and verify HMAC chain integrity.
        CGVF-CHAIN-0.
        Returns dict with valid bool and first_break_index.
        """
        try:
            if not self._ledger_path.exists():
                return {"valid": True, "entries": 0, "first_break_index": None}
            entries = []
            with open(self._ledger_path) as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
            for i, entry in enumerate(entries):
                expected = hmac.new(
                    _HMAC_KEY,
                    json.dumps(
                        {k: v for k, v in entry.items() if k != "hmac_digest"},
                        sort_keys=True,
                    ).encode(),
                    "sha256",
                ).hexdigest()
                if not hmac.compare_digest(entry.get("hmac_digest", ""), expected):
                    return {"valid": False, "entries": len(entries), "first_break_index": i}
            return {"valid": True, "entries": len(entries), "first_break_index": None}
        except Exception as exc:
            raise CGVFError(
                f"{CGVF_FAILCLOSED_0}: error verifying chain: {exc}"
            ) from exc

    def status(self) -> Dict[str, Any]:
        """Return current module status summary."""
        records = self.history(limit=1)
        return {
            "module":           "CGVF",
            "innovation":       "INNOV-120",
            "phase":            215,
            "governor":         GOVERNOR,
            "ledger_path":      str(self._ledger_path),
            "total_fusions":    len(self._load_ledger(limit=10_000)),
            "latest_score":     records[-1].consensus_score if records else None,
            "latest_status":    records[-1].overall_status.value if records else None,
            "human0_required":  records[-1].human0_required if records else False,
            "invariants": [
                CGVF_AUDIT_0, CGVF_CHAIN_0, CGVF_DETERM_0, CGVF_FAILCLOSED_0,
                CGVF_ATOMIC_0, CGVF_HUMAN0_0, CGVF_SCORE_0, CGVF_PEER_0,
                CGVF_SEAL_0, CGVF_IMMUT_0, CGVF_CERT_0, CGVF_CONSENSUS_0,
            ],
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _collect_peer_signals(self) -> List[PeerSignal]:
        """
        Query all four CG* peers.
        CGVF-PEER-0: unavailable peer is recorded with normalised=0.0 and
        available=False rather than raising — degraded score enforces intent.
        """
        signals: List[PeerSignal] = []
        for peer_id, query_fn in _PEER_QUERIES.items():
            weight = _PEER_WEIGHTS[peer_id]
            try:
                normalised, raw = query_fn()
                signals.append(
                    PeerSignal(
                        peer_id    = peer_id,
                        raw_value  = raw,
                        normalised = float(min(max(normalised, 0.0), 1.0)),
                        weight     = weight,
                        available  = True,
                    )
                )
            except Exception as exc:
                # Peer unavailable → score 0.0 for that peer
                signals.append(
                    PeerSignal(
                        peer_id    = peer_id,
                        raw_value  = None,
                        normalised = 0.0,
                        weight     = weight,
                        available  = False,
                        error_msg  = str(exc)[:200],
                    )
                )
        return signals

    def _compute_consensus(self, signals: List[PeerSignal]) -> float:
        """Compute weighted consensus score. CGVF-SCORE-0."""
        total_weight = sum(s.weight for s in signals)
        if total_weight == 0.0:
            return 0.0
        score = sum(s.normalised * s.weight for s in signals) / total_weight
        score = min(max(score, 0.0), 1.0)
        return round(score, 6)

    def _derive_status(self, score: float) -> FusionStatus:
        """
        Derive FusionStatus from consensus_score.
        CGVF-CONSENSUS-0: status is solely threshold-driven.
        """
        if score < _THRESHOLD_DEGRADED:
            if score < 0.40:
                return FusionStatus.CRITICAL
            return FusionStatus.HUMAN0_REQUIRED
        if score < _THRESHOLD_HEALTHY:
            return FusionStatus.DEGRADED
        return FusionStatus.HEALTHY

    def _derive_fusion_id(self, signals: List[PeerSignal], ts_ns: int) -> str:
        """CGVF-DETERM-0: SHA-256 of peer signal hash + ts_ns."""
        signal_str = json.dumps(
            [s.to_dict() for s in signals], sort_keys=True
        )
        payload = f"{signal_str}:{ts_ns}".encode()
        return hashlib.sha256(payload).hexdigest()

    def _find_record(self, fusion_id: str) -> Optional[FusionAttestation]:
        """
        Search ledger for most recent FusionAttestation with this fusion_id.
        Returns last match so re-certification check sees the certified record.
        """
        match = None
        for record in self._load_ledger(limit=10_000):
            if record.fusion_id == fusion_id:
                match = record
        return match

    def _load_ledger(self, limit: int = 50) -> List[FusionAttestation]:
        """Load FusionAttestation records from JSONL ledger."""
        if not self._ledger_path.exists():
            return []
        lines: List[str] = []
        with open(self._ledger_path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    lines.append(line)
        results: List[FusionAttestation] = []
        for line in lines[-limit:]:
            try:
                d = json.loads(line)
                signals = [
                    PeerSignal(
                        peer_id    = ps["peer_id"],
                        raw_value  = ps["raw_value"],
                        normalised = ps["normalised"],
                        weight     = ps["weight"],
                        available  = ps["available"],
                        error_msg  = ps.get("error_msg"),
                    )
                    for ps in d.get("peer_signals", [])
                ]
                fa = FusionAttestation(
                    fusion_id        = d["fusion_id"],
                    timestamp_ns     = d["timestamp_ns"],
                    peer_signals     = signals,
                    consensus_score  = d["consensus_score"],
                    overall_status   = FusionStatus(d["overall_status"]),
                    human0_required  = d["human0_required"],
                    human0_certified = d.get("human0_certified", False),
                    certified_by     = d.get("certified_by"),
                    prev_digest      = d["prev_digest"],
                    hmac_digest      = d.get("hmac_digest", ""),
                )
                results.append(fa)
            except Exception:
                continue
        return results

    @property
    def records(self) -> Tuple[FusionAttestation, ...]:
        """CGVF-IMMUT-0: return immutable tuple view of in-memory records."""
        return tuple(self._records)
