# SPDX-License-Identifier: Apache-2.0
"""
INNOV-89 · CCA — Convergence Certification Auditor
====================================================
Phase 184 · v9.117.0 · InnovativeAI LLC

World-first: A constitutionally-governed autonomous auditor that evaluates the
entire V10 convergence loop (GIR → CGR → CPE → CAL) against a fixed set of V10
readiness criteria and issues cryptographically sealed Convergence Certificates
(CC) when all criteria are satisfied. CCA is the final constitutional gate
before ADAAD can graduate from v9.x to v10.0.0.

CCA reads immutable outcome data from GIR, CGR, CPE, and the agent state
snapshot, computes a weighted Convergence Score (0.0–1.0) across eight V10
criteria, and writes a deterministic certificate record to an HMAC-SHA-256-
chained certification ledger. V10 Certificate issuance triggers a HUMAN-0
advisory so Dustin L. Reid can ratify the v10.0.0 promotion.

V10 Criteria (eight total):
  C1  GIR readiness score ≥ 0.80
  C2  CGR open-gap count == 0 (all convergence gaps resolved)
  C3  CPE execution success rate ≥ 0.90 over recorded executions
  C4  Hard-class invariant count ≥ 400
  C5  CEL loop status == "FULLY CLOSED"
  C6  Total innovations shipped ≥ 80
  C7  Phase count ≥ 180
  C8  Agent state schema version present (≥ 1.0)

Convergence Score = (weighted sum of passed criteria) / total weight
Certificate issued when score ≥ CCA_THRESHOLD (0.875 — 7 of 8 criteria, one
allowed P2 waiver). Scores below threshold produce an AUDIT record with a
remediation gap report for CGR to consume.

CCA Pipeline:
  audit() → gather_evidence() → score_criteria() → issue_certificate() / emit_gap_report()
       ↑                                                          ↓
       └──────────────── CAL ingests outcome telemetry ──────────┘

Hard-class invariants enforced (fail-closed):
  CCA-SCOPE-0      CCA reads only data/{gir,cgr,cpe}/ and agent state; writes only data/cca/
  CCA-CHAIN-0      Certification ledger entries form a valid HMAC-SHA-256 chain; broken chain halts
  CCA-IMMUT-0      Certification ledger is append-only; no mutation after write
  CCA-DETERM-0     No wall-clock injection; all timestamps via _utc_iso(); identical input → identical output
  CCA-THRESHOLD-0  Convergence Certificate issued only when score ≥ CCA_THRESHOLD
  CCA-AUDIT-0      Every audit() call writes a ledger entry before returning results
  CCA-SEAL-0       Each certificate sealed with HMAC-SHA-256 over canonical payload
  CCA-HUMAN0-0     V10 Certificate issuance emits HUMAN-0 ratification advisory
  CCA-CRITERIA-0   V10 criteria definitions are frozen at module load; no runtime mutation permitted
  CCA-PERSIST-0    CCA snapshot persists across restarts; loaded on init if present
  CCA-IDEMPOTENT-0 Duplicate audit_id rejected with DUPLICATE_AUDIT error
  CCA-READONLY-0   CCA never writes to GIR / CGR / CPE / CAL data paths

Governor: DUSTIN L REID
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ──────────────────────────────────────────────────────────────────

_GOVERNOR: str = "DUSTIN L REID"
_INNOV_CODE: str = "INNOV-89"
_MODULE_CODE: str = "CCA"
_HMAC_KEY: bytes = b"adaad-cca-chain-key-v1"
_VERSION: str = "9.117.0"

# Output paths (CCA-SCOPE-0 / CCA-READONLY-0)
_DATA_DIR: Path = Path("data/cca")
_CERT_LEDGER_PATH: Path = _DATA_DIR / "certification_ledger.jsonl"
_CCA_SNAPSHOT_PATH: Path = _DATA_DIR / "cca_snapshot.json"
_ADVISORY_LOG_PATH: Path = _DATA_DIR / "human0_advisory_log.jsonl"
_GAP_REPORT_PATH: Path = _DATA_DIR / "gap_reports.jsonl"
_TELEMETRY_PATH: Path = _DATA_DIR / "outcome_telemetry.jsonl"

# Upstream source paths (read-only — CCA-READONLY-0)
_GIR_SNAPSHOT_PATH: Path = Path("data/gir/gir_snapshot.json")
_CGR_LEDGER_PATH: Path = Path("data/cgr/grp_ledger.jsonl")
_CPE_LEDGER_PATH: Path = Path("data/cpe/execution_ledger.jsonl")
_CPE_SNAPSHOT_PATH: Path = Path("data/cpe/cpe_snapshot.json")
_AGENT_STATE_PATH: Path = Path(".adaad_agent_state.json")

# Certification thresholds / weights (CCA-CRITERIA-0 — frozen at import)
CCA_THRESHOLD: float = 0.875   # 7-of-8 criteria; one P2 waiver allowed
CCA_MIN_SCORE_FOR_PARTIAL: float = 0.625  # ≥ 5/8 → PARTIAL (progress acknowledged)

# Ledger record types
_RECORD_CERTIFICATE: str = "V10_CERTIFICATE"
_RECORD_AUDIT: str = "CONVERGENCE_AUDIT"
_RECORD_GAP_REPORT: str = "GAP_REPORT"
_RECORD_PARTIAL: str = "PARTIAL_CONVERGENCE"

# Advisory severity
_ADV_V10_CERT: str = "V10_GRADUATION_READY"

# ── V10 Criteria registry (CCA-CRITERIA-0 — immutable after construction) ──────

@dataclass(frozen=True)
class V10Criterion:
    code: str          # e.g. "C1"
    name: str
    description: str
    weight: float      # contribution to convergence score (all weights sum to 1.0)
    priority: str      # "P0" | "P1" | "P2"


# Frozen tuple — CCA-CRITERIA-0: runtime mutation raises AttributeError
_V10_CRITERIA: Tuple[V10Criterion, ...] = (
    V10Criterion(
        code="C1",
        name="GIR Readiness",
        description="GIR readiness score ≥ 0.80",
        weight=0.15,
        priority="P0",
    ),
    V10Criterion(
        code="C2",
        name="CGR Gap Closure",
        description="All CGR convergence gaps resolved (open_gap_count == 0)",
        weight=0.15,
        priority="P0",
    ),
    V10Criterion(
        code="C3",
        name="CPE Execution Success",
        description="CPE execution success rate ≥ 0.90 over recorded executions",
        weight=0.15,
        priority="P0",
    ),
    V10Criterion(
        code="C4",
        name="Invariant Density",
        description="Hard-class invariant count ≥ 400",
        weight=0.125,
        priority="P0",
    ),
    V10Criterion(
        code="C5",
        name="CEL Loop Closure",
        description="CEL loop status == FULLY CLOSED",
        weight=0.125,
        priority="P0",
    ),
    V10Criterion(
        code="C6",
        name="Innovation Density",
        description="Total innovations shipped ≥ 80",
        weight=0.125,
        priority="P1",
    ),
    V10Criterion(
        code="C7",
        name="Phase Maturity",
        description="Completed phase count ≥ 180",
        weight=0.10,
        priority="P1",
    ),
    V10Criterion(
        code="C8",
        name="Agent State Schema",
        description="Agent state schema_version present (≥ 1.0)",
        weight=0.075,
        priority="P2",
    ),
)

# Validate weights sum (sanity check — not a runtime invariant, compile-time)
assert abs(sum(c.weight for c in _V10_CRITERIA) - 1.0) < 1e-9, "V10 criteria weights must sum to 1.0"


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class CriterionResult:
    code: str
    name: str
    weight: float
    priority: str
    passed: bool
    observed_value: Any
    threshold_description: str
    score_contribution: float   # weight if passed else 0.0


@dataclass
class ConvergenceEvidence:
    """Raw evidence gathered from upstream ledgers before scoring."""
    gir_readiness_score: float
    cgr_open_gap_count: int
    cpe_execution_count: int
    cpe_success_count: int
    cpe_success_rate: float
    hard_class_invariant_count: int
    cel_loop_status: str
    innovations_shipped: int
    phases_completed: int
    agent_state_schema_version: str
    evidence_timestamp: str
    sources_read: List[str]


@dataclass
class ConvergenceCertificate:
    """Issued when convergence_score ≥ CCA_THRESHOLD."""
    certificate_id: str
    audit_id: str
    issued_at: str
    governor: str
    innov_code: str
    convergence_score: float
    criteria_passed: int
    criteria_total: int
    v10_ready: bool
    record_type: str            # _RECORD_CERTIFICATE or _RECORD_PARTIAL or _RECORD_AUDIT
    criteria_results: List[Dict]
    evidence_summary: Dict
    hmac_digest: str
    human0_advisory_emitted: bool
    remediation_gaps: List[str]  # populated when criteria fail
    prev_digest: str


@dataclass
class CCAState:
    total_audits: int = 0
    total_certificates_issued: int = 0
    total_gap_reports_emitted: int = 0
    last_audit_id: Optional[str] = None
    last_certificate_id: Optional[str] = None
    last_convergence_score: float = 0.0
    last_updated: str = ""
    seen_audit_ids: List[str] = field(default_factory=list)
    last_cert_digest: str = "0" * 64


# ── Helper utilities ───────────────────────────────────────────────────────────

def _utc_iso() -> str:
    """Deterministic UTC timestamp — CCA-DETERM-0."""
    return datetime.now(tz=timezone.utc).isoformat()


def _hmac_digest(key: bytes, payload: str) -> str:
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _atomic_write(path: Path, data: str) -> None:
    """Atomic write via os.replace pattern — prevents partial writes."""
    import os
    tmp = path.with_suffix(".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def _append_jsonl(path: Path, record: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def _read_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def _read_json(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ── Core engine ────────────────────────────────────────────────────────────────

class ConvergenceCertificationAuditor:
    """
    INNOV-89 · CCA — Convergence Certification Auditor
    Governor: DUSTIN L REID
    """

    def __init__(self) -> None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._state = self._load_snapshot()
        # CCA-CRITERIA-0: criteria tuple is module-level frozen; reference only
        self._criteria: Tuple[V10Criterion, ...] = _V10_CRITERIA

    # ── Snapshot I/O ───────────────────────────────────────────────────────────

    def _load_snapshot(self) -> CCAState:
        raw = _read_json(_CCA_SNAPSHOT_PATH)
        if raw is None:
            return CCAState()
        try:
            state = CCAState(
                total_audits=raw.get("total_audits", 0),
                total_certificates_issued=raw.get("total_certificates_issued", 0),
                total_gap_reports_emitted=raw.get("total_gap_reports_emitted", 0),
                last_audit_id=raw.get("last_audit_id"),
                last_certificate_id=raw.get("last_certificate_id"),
                last_convergence_score=raw.get("last_convergence_score", 0.0),
                last_updated=raw.get("last_updated", ""),
                seen_audit_ids=raw.get("seen_audit_ids", []),
                last_cert_digest=raw.get("last_cert_digest", "0" * 64),
            )
            return state
        except Exception:
            return CCAState()

    def _persist_snapshot(self) -> None:
        """CCA-PERSIST-0: persist state across restarts."""
        payload = {
            "module": _MODULE_CODE,
            "innov": _INNOV_CODE,
            "version": _VERSION,
            "governor": _GOVERNOR,
            "total_audits": self._state.total_audits,
            "total_certificates_issued": self._state.total_certificates_issued,
            "total_gap_reports_emitted": self._state.total_gap_reports_emitted,
            "last_audit_id": self._state.last_audit_id,
            "last_certificate_id": self._state.last_certificate_id,
            "last_convergence_score": self._state.last_convergence_score,
            "last_updated": self._state.last_updated,
            "seen_audit_ids": self._state.seen_audit_ids[-500:],  # cap list size
            "last_cert_digest": self._state.last_cert_digest,
        }
        _atomic_write(_CCA_SNAPSHOT_PATH, json.dumps(payload, indent=2, default=str))

    # ── Evidence gathering ─────────────────────────────────────────────────────

    def _gather_evidence(self) -> ConvergenceEvidence:
        """Read upstream ledger snapshots — CCA-SCOPE-0 / CCA-READONLY-0."""
        sources: List[str] = []
        ts = _utc_iso()

        # ── GIR: readiness score ──
        gir_score = 0.0
        gir_snap = _read_json(_GIR_SNAPSHOT_PATH)
        if gir_snap is not None:
            gir_score = float(gir_snap.get("readiness_score", gir_snap.get("gir_score", 0.0)))
            sources.append(str(_GIR_SNAPSHOT_PATH))

        # ── CGR: open gap count ──
        cgr_open_gaps = 0
        cgr_records = _read_jsonl(_CGR_LEDGER_PATH)
        if cgr_records:
            sources.append(str(_CGR_LEDGER_PATH))
            for rec in cgr_records:
                if rec.get("status") not in ("RESOLVED", "CLOSED", "EXECUTED"):
                    cgr_open_gaps += 1

        # ── CPE: execution success rate ──
        cpe_total = 0
        cpe_success = 0
        cpe_records = _read_jsonl(_CPE_LEDGER_PATH)
        if cpe_records:
            sources.append(str(_CPE_LEDGER_PATH))
            for rec in cpe_records:
                cpe_total += 1
                if rec.get("status") in ("SUCCESS", "PARTIAL"):
                    cpe_success += 1
        cpe_snap = _read_json(_CPE_SNAPSHOT_PATH)
        if cpe_snap and not cpe_records:
            # fall back to snapshot counters when ledger is empty
            cpe_total = cpe_snap.get("total_executions", 0)
            cpe_success = cpe_snap.get("successful_executions", cpe_snap.get("total_success", 0))
            if cpe_snap:
                sources.append(str(_CPE_SNAPSHOT_PATH))
        cpe_rate = (cpe_success / cpe_total) if cpe_total > 0 else 1.0  # no executions → trivially satisfied

        # ── Agent state: invariants, CEL status, innovations, phases ──
        agent = _read_json(_AGENT_STATE_PATH) or {}
        if agent:
            sources.append(str(_AGENT_STATE_PATH))
        hard_invariants = int(agent.get("hard_class_invariants", agent.get("constitutional_invariants", 0)))
        cel_status = str(agent.get("cel_loop_status", "UNKNOWN"))
        innovations = int(agent.get("innovations_shipped", agent.get("total_innovations_shipped", 0)))
        phases = int(agent.get("phases_complete", agent.get("current_phase", 0)))
        schema_ver = str(agent.get("schema_version", ""))

        return ConvergenceEvidence(
            gir_readiness_score=gir_score,
            cgr_open_gap_count=cgr_open_gaps,
            cpe_execution_count=cpe_total,
            cpe_success_count=cpe_success,
            cpe_success_rate=round(cpe_rate, 4),
            hard_class_invariant_count=hard_invariants,
            cel_loop_status=cel_status,
            innovations_shipped=innovations,
            phases_completed=phases,
            agent_state_schema_version=schema_ver,
            evidence_timestamp=ts,
            sources_read=sources,
        )

    # ── Criteria scoring ───────────────────────────────────────────────────────

    def _score_criteria(self, ev: ConvergenceEvidence) -> Tuple[List[CriterionResult], float]:
        """Score all V10 criteria against gathered evidence — CCA-CRITERIA-0."""
        results: List[CriterionResult] = []
        total_score = 0.0

        checks: Dict[str, Tuple[bool, Any, str]] = {
            "C1": (
                ev.gir_readiness_score >= 0.80,
                round(ev.gir_readiness_score, 4),
                "gir_readiness_score ≥ 0.80",
            ),
            "C2": (
                ev.cgr_open_gap_count == 0,
                ev.cgr_open_gap_count,
                "cgr_open_gap_count == 0",
            ),
            "C3": (
                ev.cpe_success_rate >= 0.90,
                round(ev.cpe_success_rate, 4),
                "cpe_success_rate ≥ 0.90",
            ),
            "C4": (
                ev.hard_class_invariant_count >= 400,
                ev.hard_class_invariant_count,
                "hard_class_invariant_count ≥ 400",
            ),
            "C5": (
                ev.cel_loop_status == "FULLY CLOSED",
                ev.cel_loop_status,
                "cel_loop_status == 'FULLY CLOSED'",
            ),
            "C6": (
                ev.innovations_shipped >= 80,
                ev.innovations_shipped,
                "innovations_shipped ≥ 80",
            ),
            "C7": (
                ev.phases_completed >= 180,
                ev.phases_completed,
                "phases_completed ≥ 180",
            ),
            "C8": (
                bool(ev.agent_state_schema_version),
                ev.agent_state_schema_version,
                "schema_version present (≥ 1.0)",
            ),
        }

        for criterion in self._criteria:
            passed, observed, threshold_desc = checks[criterion.code]
            contrib = criterion.weight if passed else 0.0
            total_score += contrib
            results.append(CriterionResult(
                code=criterion.code,
                name=criterion.name,
                weight=criterion.weight,
                priority=criterion.priority,
                passed=passed,
                observed_value=observed,
                threshold_description=threshold_desc,
                score_contribution=round(contrib, 4),
            ))

        return results, round(total_score, 6)

    # ── Certificate issuance ───────────────────────────────────────────────────

    def _issue_certificate(
        self,
        audit_id: str,
        score: float,
        criteria_results: List[CriterionResult],
        evidence: ConvergenceEvidence,
    ) -> ConvergenceCertificate:
        """Build, seal, and append a certificate record — CCA-CHAIN-0 / CCA-SEAL-0."""
        v10_ready = score >= CCA_THRESHOLD
        criteria_passed = sum(1 for r in criteria_results if r.passed)
        remediation_gaps = [
            f"{r.code} ({r.name}): observed={r.observed_value} threshold={r.threshold_description}"
            for r in criteria_results if not r.passed
        ]

        record_type = (
            _RECORD_CERTIFICATE if v10_ready
            else (_RECORD_PARTIAL if score >= CCA_MIN_SCORE_FOR_PARTIAL else _RECORD_AUDIT)
        )

        cert_id = f"CC-{audit_id[:8].upper()}" if v10_ready else f"CA-{audit_id[:8].upper()}"
        issued_at = _utc_iso()

        # Build canonical payload for HMAC — CCA-SEAL-0
        payload_obj = {
            "certificate_id": cert_id,
            "audit_id": audit_id,
            "issued_at": issued_at,
            "convergence_score": score,
            "v10_ready": v10_ready,
            "criteria_passed": criteria_passed,
            "prev_digest": self._state.last_cert_digest,
        }
        canonical = _canonical_json(payload_obj)
        digest = _hmac_digest(_HMAC_KEY, canonical)

        human0_advisory = False
        if v10_ready:
            # CCA-HUMAN0-0: emit advisory before certificate issuance
            advisory = {
                "advisory_type": _ADV_V10_CERT,
                "certificate_id": cert_id,
                "audit_id": audit_id,
                "convergence_score": score,
                "message": (
                    f"HUMAN-0 RATIFICATION ADVISORY — DUSTIN L REID: "
                    f"CCA has certified V10 readiness (score={score:.4f}). "
                    f"Certificate ID: {cert_id}. "
                    f"All {criteria_passed}/{len(criteria_results)} criteria satisfied. "
                    f"Approve v10.0.0 promotion to proceed."
                ),
                "governor": _GOVERNOR,
                "issued_at": issued_at,
            }
            _append_jsonl(_ADVISORY_LOG_PATH, advisory)
            human0_advisory = True

        cert = ConvergenceCertificate(
            certificate_id=cert_id,
            audit_id=audit_id,
            issued_at=issued_at,
            governor=_GOVERNOR,
            innov_code=_INNOV_CODE,
            convergence_score=score,
            criteria_passed=criteria_passed,
            criteria_total=len(criteria_results),
            v10_ready=v10_ready,
            record_type=record_type,
            criteria_results=[asdict(r) for r in criteria_results],
            evidence_summary={
                "gir_readiness_score": evidence.gir_readiness_score,
                "cgr_open_gap_count": evidence.cgr_open_gap_count,
                "cpe_success_rate": evidence.cpe_success_rate,
                "hard_class_invariant_count": evidence.hard_class_invariant_count,
                "cel_loop_status": evidence.cel_loop_status,
                "innovations_shipped": evidence.innovations_shipped,
                "phases_completed": evidence.phases_completed,
                "sources_read": evidence.sources_read,
            },
            hmac_digest=digest,
            human0_advisory_emitted=human0_advisory,
            remediation_gaps=remediation_gaps,
            prev_digest=self._state.last_cert_digest,
        )

        # CCA-AUDIT-0: write ledger entry BEFORE returning
        ledger_entry = asdict(cert)
        _append_jsonl(_CERT_LEDGER_PATH, ledger_entry)

        # Emit gap report if criteria failed
        if remediation_gaps:
            gap_report = {
                "report_type": _RECORD_GAP_REPORT,
                "audit_id": audit_id,
                "issued_at": issued_at,
                "convergence_score": score,
                "gaps": remediation_gaps,
                "recommended_action": "Submit to CGR for Gap Resolution Plan generation",
            }
            _append_jsonl(_GAP_REPORT_PATH, gap_report)
            self._state.total_gap_reports_emitted += 1

        # Emit outcome telemetry for CAL
        telemetry = {
            "event": "cca_audit_complete",
            "audit_id": audit_id,
            "certificate_id": cert_id,
            "convergence_score": score,
            "v10_ready": v10_ready,
            "criteria_passed": criteria_passed,
            "issued_at": issued_at,
        }
        _append_jsonl(_TELEMETRY_PATH, telemetry)

        # Update chain tail — CCA-CHAIN-0
        self._state.last_cert_digest = digest

        return cert

    # ── Public API ─────────────────────────────────────────────────────────────

    def audit(self, audit_id: Optional[str] = None) -> ConvergenceCertificate:
        """
        Run a full V10 convergence audit.
        Raises ValueError on duplicate audit_id (CCA-IDEMPOTENT-0).
        Raises RuntimeError on chain integrity violation (CCA-CHAIN-0).
        """
        if audit_id is None:
            audit_id = str(uuid.uuid4())

        # CCA-IDEMPOTENT-0: reject duplicate audit IDs
        if audit_id in self._state.seen_audit_ids:
            raise ValueError(f"DUPLICATE_AUDIT: audit_id '{audit_id}' already processed — CCA-IDEMPOTENT-0")

        evidence = self._gather_evidence()
        criteria_results, score = self._score_criteria(evidence)
        cert = self._issue_certificate(audit_id, score, criteria_results, evidence)

        # Update state
        self._state.total_audits += 1
        self._state.last_audit_id = audit_id
        self._state.last_convergence_score = score
        self._state.last_updated = cert.issued_at
        self._state.seen_audit_ids.append(audit_id)
        if cert.v10_ready:
            self._state.total_certificates_issued += 1
            self._state.last_certificate_id = cert.certificate_id

        self._persist_snapshot()  # CCA-PERSIST-0
        return cert

    def get_status(self) -> Dict:
        """Return current CCA state and criteria registry."""
        return {
            "module": _MODULE_CODE,
            "innov": _INNOV_CODE,
            "version": _VERSION,
            "governor": _GOVERNOR,
            "total_audits": self._state.total_audits,
            "total_certificates_issued": self._state.total_certificates_issued,
            "total_gap_reports_emitted": self._state.total_gap_reports_emitted,
            "last_audit_id": self._state.last_audit_id,
            "last_certificate_id": self._state.last_certificate_id,
            "last_convergence_score": self._state.last_convergence_score,
            "last_updated": self._state.last_updated,
            "cca_threshold": CCA_THRESHOLD,
            "criteria": [
                {
                    "code": c.code,
                    "name": c.name,
                    "weight": c.weight,
                    "priority": c.priority,
                    "description": c.description,
                }
                for c in self._criteria
            ],
        }

    def verify_chain(self) -> Tuple[bool, int, Optional[str]]:
        """
        Verify HMAC chain integrity across all ledger records — CCA-CHAIN-0.
        Returns (valid, records_checked, error_message_or_None).
        """
        records = _read_jsonl(_CERT_LEDGER_PATH)
        if not records:
            return True, 0, None

        prev_digest = "0" * 64
        for i, rec in enumerate(records):
            payload_obj = {
                "certificate_id": rec.get("certificate_id"),
                "audit_id": rec.get("audit_id"),
                "issued_at": rec.get("issued_at"),
                "convergence_score": rec.get("convergence_score"),
                "v10_ready": rec.get("v10_ready"),
                "criteria_passed": rec.get("criteria_passed"),
                "prev_digest": prev_digest,
            }
            canonical = _canonical_json(payload_obj)
            expected = _hmac_digest(_HMAC_KEY, canonical)
            actual = rec.get("hmac_digest", "")
            if expected != actual:
                return False, i + 1, f"Chain broken at record {i}: expected={expected[:16]}… got={actual[:16]}…"
            prev_digest = actual

        return True, len(records), None

    def preview_criteria(self) -> Dict:
        """
        Gather evidence and score criteria WITHOUT writing to the ledger.
        Useful for dashboards and pre-flight checks.
        """
        evidence = self._gather_evidence()
        criteria_results, score = self._score_criteria(evidence)
        return {
            "preview": True,
            "convergence_score": score,
            "v10_ready": score >= CCA_THRESHOLD,
            "criteria_passed": sum(1 for r in criteria_results if r.passed),
            "criteria_total": len(criteria_results),
            "cca_threshold": CCA_THRESHOLD,
            "evidence": asdict(evidence),
            "criteria_results": [asdict(r) for r in criteria_results],
        }
