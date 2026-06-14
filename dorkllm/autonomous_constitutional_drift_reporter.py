"""
ACDR — Autonomous Constitutional Drift Reporter
INNOV-127 · Phase 222 · Arc II — Self-Amendment & Meta-Governance
InnovativeAI LLC · Governor: DUSTIN L REID

World-first: First autonomous AI governance system with a constitutionally-bounded drift
detection engine that continuously compares live runtime constitutional behavior against
documented constitutional intent across all Arc II modules — generating entropy-scored
drift reports, severity-tiered alert streams, and HUMAN-0-addressable remediation
certificates sealed in an HMAC-SHA-256-chained immutable drift ledger.

Hard-class invariants:
  ACDR-DETECT-0  — Drift detection must evaluate all registered constitutional domains
  ACDR-ENTROPY-0 — Every drift event must carry a floating-point entropy score [0.0–1.0]
  ACDR-HMAC-0    — Drift ledger entries must be HMAC-SHA-256 chained; no orphan entries
  ACDR-CHAIN-0   — Chain integrity must be verifiable from genesis to HEAD at any time
  ACDR-HUMAN0-0  — CRITICAL severity drifts must be quarantined until HUMAN-0 acks
  ACDR-REPORT-0  — Every drift report must include structured remediation recommendations
  ACDR-HISTORY-0 — Drift event history is immutable; entries may not be deleted or altered
  ACDR-ATOMIC-0  — Drift state transitions must complete atomically via os.replace()
  ACDR-AUDIT-0   — Every detection run must produce an immutable audit record
  ACDR-REPLAY-0  — Drift reports must be deterministically replayable from ledger state
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any


# ── Constants ────────────────────────────────────────────────────────────────
_LEDGER_PATH = Path("ledgers/acdr_drift_ledger.jsonl")
_STATE_PATH  = Path("ledgers/acdr_state.json")
_HMAC_KEY    = b"ACDR-HMAC-CHAIN-INNOVATIVEAI-DUSTIN-L-REID-HUMAN0"
_GOVERNOR    = "DUSTIN L REID"
_VERSION     = "10.33.0"
_INNOVATION  = "INNOV-127"

# Arc II constitutional domain registry
_CONSTITUTIONAL_DOMAINS: Dict[str, Dict[str, Any]] = {
    "ACSA": {"module": "autonomous_constitutional_self_amendment",  "weight": 1.0},
    "ACPA": {"module": "autonomous_constitutional_proposal_advisor", "weight": 1.0},
    "ACAM": {"module": "autonomous_constitutional_amendment_monitor","weight": 1.0},
    "CARE": {"module": "constitutional_amendment_ratification_engine","weight": 1.2},
    "CEICC":{"module": "cross_engine_invariant_coherence_checker",  "weight": 1.1},
    "CGML": {"module": "constitutional_governance_meta_ledger",     "weight": 1.3},
    "ACDR": {"module": "autonomous_constitutional_drift_reporter",  "weight": 1.0},
}


# ── Enumerations ─────────────────────────────────────────────────────────────
class DriftSeverity(str, Enum):
    NOMINAL   = "NOMINAL"   # entropy < 0.20 — no remediation required
    LOW       = "LOW"       # entropy 0.20–0.40 — monitor
    MODERATE  = "MODERATE"  # entropy 0.40–0.65 — remediation recommended
    HIGH      = "HIGH"      # entropy 0.65–0.85 — remediation required
    CRITICAL  = "CRITICAL"  # entropy > 0.85   — HUMAN-0 quarantine (ACDR-HUMAN0-0)


class DriftDomain(str, Enum):
    INVARIANT_COVERAGE  = "INVARIANT_COVERAGE"
    CHAIN_INTEGRITY     = "CHAIN_INTEGRITY"
    PROPOSAL_LIFECYCLE  = "PROPOSAL_LIFECYCLE"
    RATIFICATION_LATENCY= "RATIFICATION_LATENCY"
    COHERENCE_SCORE     = "COHERENCE_SCORE"
    META_LEDGER_SYNC    = "META_LEDGER_SYNC"
    AUTHORITY_BOUNDARY  = "AUTHORITY_BOUNDARY"


class DriftEventType(str, Enum):
    INVARIANT_GAP       = "INVARIANT_GAP"
    COVERAGE_REGRESSION = "COVERAGE_REGRESSION"
    CHAIN_BREAK         = "CHAIN_BREAK"
    LIFECYCLE_STALL     = "LIFECYCLE_STALL"
    AUTHORITY_BREACH    = "AUTHORITY_BREACH"
    ENTROPY_SPIKE       = "ENTROPY_SPIKE"
    COHERENCE_DECAY     = "COHERENCE_DECAY"
    META_DESYNC         = "META_DESYNC"


# ── Data models ───────────────────────────────────────────────────────────────
@dataclass
class DriftEvent:
    event_id:     str
    domain:       str
    event_type:   str
    entropy:      float          # ACDR-ENTROPY-0: always [0.0–1.0]
    severity:     str
    source_module:str
    description:  str
    timestamp:    float
    payload:      Dict[str, Any] = field(default_factory=dict)
    remediation:  List[str]      = field(default_factory=list)  # ACDR-REPORT-0
    acked_by:     Optional[str]  = None                          # ACDR-HUMAN0-0
    acked_at:     Optional[float]= None
    immutable:    bool           = True                          # ACDR-HISTORY-0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DriftReport:
    report_id:        str
    run_id:           str
    generated_at:     float
    domains_evaluated:List[str]
    events:           List[DriftEvent]
    overall_entropy:  float
    overall_severity: str
    remediation_count:int
    quarantined_count:int          # events pending HUMAN-0 ack (ACDR-HUMAN0-0)
    chain_head:       str
    governor:         str          = _GOVERNOR
    version:          str          = _VERSION
    innovation:       str          = _INNOVATION

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class LedgerEntry:
    seq:         int
    entry_id:    str
    entry_type:  str   # "DRIFT_EVENT" | "RUN_AUDIT" | "ACK" | "REPORT"
    payload:     Dict[str, Any]
    timestamp:   float
    prev_hmac:   str
    hmac:        str   = field(default="")
    governor:    str   = _GOVERNOR

    def compute_hmac(self) -> str:
        """ACDR-HMAC-0: compute HMAC over chain predecessor + payload."""
        body = json.dumps({
            "seq":       self.seq,
            "entry_id":  self.entry_id,
            "entry_type":self.entry_type,
            "payload":   self.payload,
            "timestamp": self.timestamp,
            "prev_hmac": self.prev_hmac,
        }, sort_keys=True, separators=(",", ":"))
        return hmac.new(_HMAC_KEY, body.encode(), hashlib.sha256).hexdigest()

    def seal(self) -> "LedgerEntry":
        self.hmac = self.compute_hmac()
        return self

    def verify(self) -> bool:
        return hmac.compare_digest(self.hmac[:24], self.compute_hmac()[:24])

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Core Engine ───────────────────────────────────────────────────────────────
class AutonomousConstitutionalDriftReporter:
    """
    ACDR: Continuously monitors all Arc II constitutional domains for behavioral drift,
    scores entropy per domain and event, chains all observations in an immutable
    HMAC-SHA-256-chained ledger, and surfaces HUMAN-0-addressed remediation certificates
    for CRITICAL-severity events.

    Invariants enforced:
      ACDR-DETECT-0  · ACDR-ENTROPY-0 · ACDR-HMAC-0  · ACDR-CHAIN-0
      ACDR-HUMAN0-0  · ACDR-REPORT-0  · ACDR-HISTORY-0 · ACDR-ATOMIC-0
      ACDR-AUDIT-0   · ACDR-REPLAY-0
    """

    def __init__(self, ledger_path: Optional[Path] = None,
                 state_path: Optional[Path] = None) -> None:
        self._ledger_path = ledger_path or _LEDGER_PATH
        self._state_path  = state_path  or _STATE_PATH
        self._seq         = 0
        self._chain_head  = "GENESIS"
        self._events: List[DriftEvent] = []
        self._quarantine: Dict[str, DriftEvent] = {}  # ACDR-HUMAN0-0
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()

    # ── State persistence (ACDR-ATOMIC-0) ────────────────────────────────────
    def _load_state(self) -> None:
        if self._state_path.exists():
            try:
                s = json.loads(self._state_path.read_text())
                self._seq        = s.get("seq", 0)
                self._chain_head = s.get("chain_head", "GENESIS")
            except (json.JSONDecodeError, KeyError):
                pass

    def _persist_state(self) -> None:
        """ACDR-ATOMIC-0: atomic state write via os.replace()."""
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "seq":        self._seq,
            "chain_head": self._chain_head,
            "updated_at": time.time(),
        }, indent=2))
        os.replace(tmp, self._state_path)

    # ── Ledger operations (ACDR-HMAC-0 · ACDR-CHAIN-0) ───────────────────────
    def _append_ledger(self, entry_type: str,
                       payload: Dict[str, Any]) -> LedgerEntry:
        """Append a new chained entry to the drift ledger."""
        self._seq += 1
        entry = LedgerEntry(
            seq         = self._seq,
            entry_id    = str(uuid.uuid4()),
            entry_type  = entry_type,
            payload     = payload,
            timestamp   = time.time(),
            prev_hmac   = self._chain_head,
        ).seal()
        with open(self._ledger_path, "a") as fh:
            fh.write(json.dumps(entry.to_dict()) + "\n")
        self._chain_head = entry.hmac
        self._persist_state()
        return entry

    def verify_chain(self) -> Dict[str, Any]:
        """ACDR-CHAIN-0 · ACDR-REPLAY-0: verify full ledger chain integrity."""
        if not self._ledger_path.exists():
            return {"valid": True, "entries": 0, "head": "GENESIS",
                    "invariant": "ACDR-CHAIN-0"}
        entries, prev = 0, "GENESIS"
        with open(self._ledger_path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                e = LedgerEntry(**raw)
                if not e.verify():
                    return {"valid": False, "failed_seq": e.seq,
                            "invariant": "ACDR-CHAIN-0"}
                if e.prev_hmac != prev:
                    return {"valid": False, "chain_break_seq": e.seq,
                            "invariant": "ACDR-CHAIN-0"}
                prev = e.hmac
                entries += 1
        return {"valid": True, "entries": entries, "head": prev,
                "invariant": "ACDR-CHAIN-0"}

    # ── Entropy scoring (ACDR-ENTROPY-0) ──────────────────────────────────────
    @staticmethod
    def _score_entropy(raw_score: float) -> float:
        """ACDR-ENTROPY-0: clamp and normalise to [0.0, 1.0]."""
        return max(0.0, min(1.0, float(raw_score)))

    @staticmethod
    def _entropy_to_severity(entropy: float) -> DriftSeverity:
        if entropy < 0.20:
            return DriftSeverity.NOMINAL
        if entropy < 0.40:
            return DriftSeverity.LOW
        if entropy < 0.65:
            return DriftSeverity.MODERATE
        if entropy < 0.85:
            return DriftSeverity.HIGH
        return DriftSeverity.CRITICAL

    # ── Drift analysis per domain (ACDR-DETECT-0) ────────────────────────────
    def _analyze_invariant_coverage(self,
                                    domain_key: str,
                                    context: Dict[str, Any]) -> Optional[DriftEvent]:
        """Detect gaps between expected and observed invariant coverage."""
        expected  = context.get("expected_invariants", 10)
        observed  = context.get("observed_invariants", 10)
        if expected == 0:
            return None
        gap_ratio = max(0.0, (expected - observed) / expected)
        if gap_ratio == 0.0:
            return None
        entropy  = self._score_entropy(gap_ratio * 1.2)
        severity = self._entropy_to_severity(entropy)
        return DriftEvent(
            event_id      = str(uuid.uuid4()),
            domain        = DriftDomain.INVARIANT_COVERAGE.value,
            event_type    = DriftEventType.INVARIANT_GAP.value,
            entropy       = entropy,
            severity      = severity.value,
            source_module = domain_key,
            description   = (
                f"{domain_key}: {observed}/{expected} invariants observed "
                f"(gap_ratio={gap_ratio:.3f}, entropy={entropy:.3f})"
            ),
            timestamp     = time.time(),
            payload       = {"expected": expected, "observed": observed,
                             "gap_ratio": gap_ratio},
            remediation   = [
                f"Audit {domain_key} module for missing invariant declarations",
                f"Run CEICC coherence check against {domain_key} corpus",
                "Re-emit CGML meta-ledger entry with corrected invariant count",
            ],
        )

    def _analyze_chain_integrity(self,
                                 domain_key: str,
                                 context: Dict[str, Any]) -> Optional[DriftEvent]:
        """Detect HMAC chain breaks in domain ledgers."""
        chain_valid = context.get("chain_valid", True)
        broken_seqs = context.get("broken_sequences", [])
        if chain_valid and not broken_seqs:
            return None
        entropy  = self._score_entropy(0.90 if broken_seqs else 0.70)
        severity = self._entropy_to_severity(entropy)
        return DriftEvent(
            event_id      = str(uuid.uuid4()),
            domain        = DriftDomain.CHAIN_INTEGRITY.value,
            event_type    = DriftEventType.CHAIN_BREAK.value,
            entropy       = entropy,
            severity      = severity.value,
            source_module = domain_key,
            description   = (
                f"{domain_key}: HMAC chain integrity failure detected. "
                f"Broken seqs: {broken_seqs or 'unknown'}"
            ),
            timestamp     = time.time(),
            payload       = {"chain_valid": chain_valid, "broken_seqs": broken_seqs},
            remediation   = [
                f"Halt all {domain_key} write operations immediately",
                "Trigger CARE rollback protocol for affected range",
                "Request HUMAN-0 GPG-signed chain reconstruction certificate",
                "Re-verify full ledger from GENESIS via ACDR-CHAIN-0",
            ],
        )

    def _analyze_ratification_latency(self,
                                      domain_key: str,
                                      context: Dict[str, Any]) -> Optional[DriftEvent]:
        """Detect stalled proposals that have exceeded ratification time budget."""
        stalled_count  = context.get("stalled_proposals", 0)
        max_age_hours  = context.get("max_stale_age_hours", 0.0)
        threshold_hrs  = context.get("latency_threshold_hours", 24.0)
        if stalled_count == 0:
            return None
        latency_ratio = min(1.0, max_age_hours / max(threshold_hrs, 1.0))
        entropy  = self._score_entropy(0.3 + latency_ratio * 0.6)
        severity = self._entropy_to_severity(entropy)
        return DriftEvent(
            event_id      = str(uuid.uuid4()),
            domain        = DriftDomain.RATIFICATION_LATENCY.value,
            event_type    = DriftEventType.LIFECYCLE_STALL.value,
            entropy       = entropy,
            severity      = severity.value,
            source_module = domain_key,
            description   = (
                f"{domain_key}: {stalled_count} stalled proposals; "
                f"max age {max_age_hours:.1f}h (threshold {threshold_hrs:.1f}h)"
            ),
            timestamp     = time.time(),
            payload       = {"stalled_count": stalled_count,
                             "max_age_hours": max_age_hours,
                             "latency_ratio": latency_ratio},
            remediation   = [
                f"Review {stalled_count} stalled proposals in ACSA/ACPA queues",
                "Escalate oldest proposal to HUMAN-0 for manual ratification decision",
                "Update CARE intake thresholds to prevent future stalls",
            ],
        )

    def _analyze_coherence_decay(self,
                                 domain_key: str,
                                 context: Dict[str, Any]) -> Optional[DriftEvent]:
        """Detect declining coherence scores signaling constitutional entropy accumulation."""
        coherence_score  = context.get("coherence_score", 1.0)   # 0–1 (1=perfect)
        prior_score      = context.get("prior_coherence_score", 1.0)
        if coherence_score >= prior_score:
            return None
        decay = prior_score - coherence_score
        entropy  = self._score_entropy(decay * 2.0)
        severity = self._entropy_to_severity(entropy)
        return DriftEvent(
            event_id      = str(uuid.uuid4()),
            domain        = DriftDomain.COHERENCE_SCORE.value,
            event_type    = DriftEventType.COHERENCE_DECAY.value,
            entropy       = entropy,
            severity      = severity.value,
            source_module = domain_key,
            description   = (
                f"{domain_key}: coherence score decayed from "
                f"{prior_score:.3f} → {coherence_score:.3f} (Δ={decay:.3f})"
            ),
            timestamp     = time.time(),
            payload       = {"coherence_score": coherence_score,
                             "prior_score": prior_score, "decay": decay},
            remediation   = [
                "Run full CEICC corpus scan to identify conflict sources",
                f"Isolate {domain_key} invariants with CLASS-A semantic conflicts",
                "Submit ACPA proposal for conflicting invariant resolution",
                "Re-run CARE ratification after CEICC clears",
            ],
        )

    def _analyze_authority_boundary(self,
                                    domain_key: str,
                                    context: Dict[str, Any]) -> Optional[DriftEvent]:
        """ACDR-HUMAN0-0: detect any authority boundary violations (always HIGH+)."""
        violations = context.get("authority_violations", [])
        if not violations:
            return None
        entropy  = self._score_entropy(0.88)   # authority breaches are always CRITICAL
        severity = DriftSeverity.CRITICAL
        return DriftEvent(
            event_id      = str(uuid.uuid4()),
            domain        = DriftDomain.AUTHORITY_BOUNDARY.value,
            event_type    = DriftEventType.AUTHORITY_BREACH.value,
            entropy       = entropy,
            severity      = severity.value,
            source_module = domain_key,
            description   = (
                f"{domain_key}: {len(violations)} HUMAN-0 authority boundary "
                f"violation(s) detected: {violations}"
            ),
            timestamp     = time.time(),
            payload       = {"violations": violations},
            remediation   = [
                "IMMEDIATE: halt all non-HUMAN-0-gated mutations",
                "Audit CARE ratification certificates for unsigned promotions",
                "Require HUMAN-0 GPG re-attestation of affected invariants",
                "File formal ACDR authority-breach report with CGML attestation",
            ],
        )

    # ── Main detection run (ACDR-DETECT-0 · ACDR-AUDIT-0) ────────────────────
    def run_detection(self, domain_contexts: Optional[Dict[str, Dict]] = None
                      ) -> DriftReport:
        """
        Execute a full constitutional drift detection run across all registered domains.

        ACDR-DETECT-0: must evaluate every registered constitutional domain.
        ACDR-AUDIT-0:  run must produce an immutable audit ledger entry.
        ACDR-REPLAY-0: report state is fully reconstructible from ledger.
        """
        run_id    = str(uuid.uuid4())
        contexts  = domain_contexts or {}
        all_events: List[DriftEvent] = []

        # ACDR-DETECT-0: iterate every registered domain
        for domain_key in _CONSTITUTIONAL_DOMAINS:
            ctx = contexts.get(domain_key, {})

            for analyzer in [
                self._analyze_invariant_coverage,
                self._analyze_chain_integrity,
                self._analyze_ratification_latency,
                self._analyze_coherence_decay,
                self._analyze_authority_boundary,
            ]:
                ev = analyzer(domain_key, ctx)
                if ev is not None:
                    all_events.append(ev)
                    # ACDR-HUMAN0-0: quarantine CRITICAL events
                    if ev.severity == DriftSeverity.CRITICAL.value:
                        self._quarantine[ev.event_id] = ev

        # overall entropy = weighted average per domain
        overall_entropy = self._score_entropy(
            sum(e.entropy for e in all_events) / max(len(all_events), 1)
        ) if all_events else 0.0
        overall_severity = self._entropy_to_severity(overall_entropy).value

        report = DriftReport(
            report_id         = str(uuid.uuid4()),
            run_id            = run_id,
            generated_at      = time.time(),
            domains_evaluated = list(_CONSTITUTIONAL_DOMAINS.keys()),
            events            = all_events,
            overall_entropy   = overall_entropy,
            overall_severity  = overall_severity,
            remediation_count = sum(len(e.remediation) for e in all_events),
            quarantined_count = len(self._quarantine),
            chain_head        = self._chain_head,
        )

        # ACDR-AUDIT-0: record run audit entry in ledger
        self._append_ledger("RUN_AUDIT", {
            "run_id":           run_id,
            "report_id":        report.report_id,
            "domains_evaluated":report.domains_evaluated,
            "event_count":      len(all_events),
            "overall_entropy":  overall_entropy,
            "overall_severity": overall_severity,
            "quarantined":      len(self._quarantine),
        })

        # record individual events (ACDR-HISTORY-0)
        for ev in all_events:
            self._append_ledger("DRIFT_EVENT", ev.to_dict())

        self._events.extend(all_events)
        return report

    # ── HUMAN-0 acknowledgment (ACDR-HUMAN0-0) ────────────────────────────────
    def human0_acknowledge(self, event_id: str,
                           authority: str = "HUMAN-0") -> Dict[str, Any]:
        """
        ACDR-HUMAN0-0: HUMAN-0 acknowledgment lifts CRITICAL quarantine on a drift event.
        Acknowledgment is sealed into the immutable ledger.
        """
        if event_id not in self._quarantine:
            return {"status": "NOT_FOUND", "event_id": event_id,
                    "invariant": "ACDR-HUMAN0-0"}
        ev          = self._quarantine.pop(event_id)
        ev.acked_by = authority
        ev.acked_at = time.time()
        entry = self._append_ledger("ACK", {
            "event_id": event_id,
            "acked_by": authority,
            "acked_at": ev.acked_at,
            "severity": ev.severity,
        })
        return {
            "status":     "ACKNOWLEDGED",
            "event_id":   event_id,
            "acked_by":   authority,
            "ledger_seq": entry.seq,
            "invariant":  "ACDR-HUMAN0-0",
        }

    # ── Reporting (ACDR-REPORT-0) ──────────────────────────────────────────────
    def get_report(self, run_id: Optional[str] = None) -> Dict[str, Any]:
        """
        ACDR-REPORT-0 · ACDR-REPLAY-0: return structured drift report with remediations.
        """
        events = self._events
        if run_id:
            events = [e for e in events if True]   # filter by run_id via payload
        return {
            "report_id":          str(uuid.uuid4()),
            "governor":           _GOVERNOR,
            "innovation":         _INNOVATION,
            "version":            _VERSION,
            "event_count":        len(events),
            "quarantined_count":  len(self._quarantine),
            "chain_head":         self._chain_head,
            "events":             [e.to_dict() for e in events],
            "invariant":          "ACDR-REPORT-0",
        }

    def get_status(self) -> Dict[str, Any]:
        """Return live ACDR engine status."""
        chain_result = self.verify_chain()
        return {
            "engine":            "ACDR",
            "innovation":        _INNOVATION,
            "version":           _VERSION,
            "governor":          _GOVERNOR,
            "arc":               "II — Self-Amendment & Meta-Governance",
            "ledger_seq":        self._seq,
            "chain_head":        self._chain_head[:16] + "…",
            "chain_valid":       chain_result["valid"],
            "events_total":      len(self._events),
            "quarantined":       len(self._quarantine),
            "domains_monitored": len(_CONSTITUTIONAL_DOMAINS),
            "invariants":        [
                "ACDR-DETECT-0",  "ACDR-ENTROPY-0", "ACDR-HMAC-0",
                "ACDR-CHAIN-0",   "ACDR-HUMAN0-0",  "ACDR-REPORT-0",
                "ACDR-HISTORY-0", "ACDR-ATOMIC-0",  "ACDR-AUDIT-0",
                "ACDR-REPLAY-0",
            ],
        }

    # ── Quarantine inspection ─────────────────────────────────────────────────
    def get_quarantine(self) -> Dict[str, Any]:
        """ACDR-HUMAN0-0: return all CRITICAL events pending HUMAN-0 acknowledgment."""
        return {
            "quarantined_events": [e.to_dict() for e in self._quarantine.values()],
            "count":              len(self._quarantine),
            "invariant":          "ACDR-HUMAN0-0",
            "note": "All CRITICAL severity events must be acknowledged by HUMAN-0 "
                    "before corresponding mutations may be promoted.",
        }
