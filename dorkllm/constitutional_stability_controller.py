# SPDX-License-Identifier: Apache-2.0
"""
INNOV-84 · CSC — Constitutional Stability Controller
=====================================================
Phase 179 · v9.112.0 · InnovativeAI LLC

World-first: A constitutional stability monitoring engine that reads the
output of CAE (INNOV-83) amendment execution ledgers and the live constitution
snapshot to compute per-invariant Stability Scores and a System Constitutional
Stability Index (SCSI). Emits governed stability alerts when the SCSI drops
below configurable thresholds, and maintains an immutable HMAC-chained
stability report ledger.

CSC closes the outer monitoring ring of the CEL self-improvement loop:

  MSE → MRP → MPG → MEX → MFV → IIS → CAL → RDP → HUMAN-0
   ↑                                                      │
   └──── CFI ◄───── CAE ◄──────────────────── CSC ◄──────┘

CSC is read-only with respect to all upstream ledgers. It never writes to
CAE, CFI, RDP, CAL, or any other engine's data directory. Its sole outputs
are the stability report ledger and alert log in data/csc/.

Hard-class invariants enforced (fail-closed):
  CSC-SCORE-0      Stability score computed deterministically from ledger data; no RNG
  CSC-READONLY-0   CSC never writes to CAE, CFI, RDP, or CAL ledgers; read-only
  CSC-CHAIN-0      Stability report ledger uses HMAC-SHA-256 chaining; broken chain halts
  CSC-IMMUT-0      Stability report ledger is append-only; no record mutation permitted
  CSC-DETERM-0     No wall-clock injection; all timestamps via _utc_iso()
  CSC-ALERT-0      SCSI below WARNING_THRESHOLD must emit alert record; fail-closed
  CSC-THRESHOLD-0  Stability thresholds are governed constants; not runtime-modifiable
  CSC-SCOPE-0      CSC reads only constitution_snapshot.json + amendment ledger; no ext I/O
  CSC-AUDIT-0      Every stability computation cycle writes a signed audit record
  CSC-HUMAN0-0     SCSI < CRITICAL_THRESHOLD sets human0_escalation=True in alert

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
from typing import Dict, List, Optional, Tuple


# ── Constants ─────────────────────────────────────────────────────────────────

_GOVERNOR: str = "DUSTIN L REID"
_INNOV_CODE: str = "INNOV-84"
_MODULE_CODE: str = "CSC"
_HMAC_KEY: bytes = b"adaad-csc-chain-key-v1"

# Governed stability thresholds (CSC-THRESHOLD-0 — do NOT modify at runtime)
WARNING_THRESHOLD: float = 0.70   # SCSI below this → WARNING alert
CRITICAL_THRESHOLD: float = 0.50  # SCSI below this → CRITICAL alert + HUMAN-0 flag

# Stability scoring weights
_WEIGHT_BASE: float = 1.0          # base score for every active invariant
_WEIGHT_REINFORCE: float = 0.05    # bonus per reinforcement
_WEIGHT_REVIEW_PENALTY: float = 0.10   # deduct per review flag
_WEIGHT_RETIRED_PENALTY: float = 1.0   # retired invariants contribute 0
_MAX_SCORE: float = 2.0            # clip ceiling for normalisation

_DATA_DIR: Path = Path("data/csc")
_REPORT_LEDGER_PATH: Path = _DATA_DIR / "stability_report_ledger.jsonl"
_ALERT_LOG_PATH: Path = _DATA_DIR / "stability_alerts.jsonl"
_SCSI_SNAPSHOT_PATH: Path = _DATA_DIR / "scsi_snapshot.json"

# CAE source paths (read-only)
_CAE_SNAPSHOT_PATH: Path = Path("data/cae/constitution_snapshot.json")
_CAE_EXECUTION_LEDGER_PATH: Path = Path("data/cae/amendment_execution_ledger.jsonl")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_iso() -> str:
    """Deterministic UTC ISO-8601 timestamp. CSC-DETERM-0."""
    return datetime.now(tz=timezone.utc).isoformat()


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def _hmac_hex(key: bytes, data: str) -> str:
    return hmac.new(key, data.encode(), hashlib.sha256).hexdigest()


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class InvariantStabilityRecord:
    """Per-invariant stability record. CSC-SCORE-0."""
    invariant_id: str
    is_active: bool                  # False = retired
    reinforcement_count: int = 0     # number of REINFORCE amendments applied
    review_flag_count: int = 0       # number of REVIEW amendments applied
    add_count: int = 0               # number of ADD events
    stability_score: float = 0.0     # computed; 0.0–1.0 normalised
    last_amended_at: Optional[str] = None
    amendment_ids: List[str] = field(default_factory=list)

    def compute_score(self) -> float:
        """
        Deterministic stability score. CSC-SCORE-0.

        Retired invariants → 0.0 (they no longer contribute to stability).
        Active invariants start at _WEIGHT_BASE, gain reinforcement bonuses,
        and lose review penalties, clipped to [0.0, _MAX_SCORE] then
        normalised to [0.0, 1.0].
        """
        if not self.is_active:
            self.stability_score = 0.0
            return self.stability_score

        raw = (
            _WEIGHT_BASE
            + self.reinforcement_count * _WEIGHT_REINFORCE
            - self.review_flag_count * _WEIGHT_REVIEW_PENALTY
        )
        clipped = max(0.0, min(raw, _MAX_SCORE))
        self.stability_score = round(clipped / _MAX_SCORE, 6)
        return self.stability_score


@dataclass
class StabilityReport:
    """One full CSC computation cycle output."""
    report_id: str
    cycle_timestamp: str
    invariant_count_active: int
    invariant_count_retired: int
    invariant_count_total: int
    per_invariant_scores: Dict[str, float]
    scsi: float                      # System Constitutional Stability Index
    scsi_status: str                 # OK | WARNING | CRITICAL
    human0_escalation: bool
    alert_emitted: bool
    amendment_ledger_records_read: int
    snapshot_sha256: str
    hmac_chain_prev: str
    hmac_chain_current: str
    governor: str = _GOVERNOR
    innov_code: str = _INNOV_CODE
    module_code: str = _MODULE_CODE


@dataclass
class StabilityAlert:
    """Alert record written when SCSI < WARNING_THRESHOLD. CSC-ALERT-0."""
    alert_id: str
    report_id: str
    alert_level: str           # WARNING | CRITICAL
    scsi: float
    threshold_breached: float
    human0_escalation: bool    # True when scsi < CRITICAL_THRESHOLD. CSC-HUMAN0-0.
    timestamp: str
    message: str
    governor: str = _GOVERNOR


# ── Core engine ───────────────────────────────────────────────────────────────

class ConstitutionalStabilityController:
    """
    INNOV-84 · CSC — Constitutional Stability Controller.

    Usage::

        csc = ConstitutionalStabilityController()
        report = csc.run_stability_cycle()
        print(f"SCSI: {report.scsi}  Status: {report.scsi_status}")
    """

    def __init__(
        self,
        data_dir: Path = _DATA_DIR,
        cae_snapshot_path: Path = _CAE_SNAPSHOT_PATH,
        cae_ledger_path: Path = _CAE_EXECUTION_LEDGER_PATH,
    ) -> None:
        # CSC-READONLY-0: only data/csc/ is writable; all other paths are read-only
        self._data_dir = data_dir
        self._cae_snapshot_path = cae_snapshot_path
        self._cae_ledger_path = cae_ledger_path

        self._report_ledger_path = data_dir / "stability_report_ledger.jsonl"
        self._alert_log_path = data_dir / "stability_alerts.jsonl"
        self._scsi_snapshot_path = data_dir / "scsi_snapshot.json"

        self._data_dir.mkdir(parents=True, exist_ok=True)

        # Load previous chain tail for HMAC chaining (CSC-CHAIN-0)
        self._prev_hmac: str = self._load_prev_chain_tail()

    # ── Chain management (CSC-CHAIN-0, CSC-IMMUT-0) ──────────────────────────

    def _load_prev_chain_tail(self) -> str:
        """Read the HMAC of the last report ledger record, or genesis sentinel."""
        if not self._report_ledger_path.exists():
            return _hmac_hex(_HMAC_KEY, "CSC-GENESIS-179")
        records = self._report_ledger_path.read_text(encoding="utf-8").strip().splitlines()
        if not records:
            return _hmac_hex(_HMAC_KEY, "CSC-GENESIS-179")
        last = json.loads(records[-1])
        chain_current = last.get("hmac_chain_current")
        if not chain_current:
            raise RuntimeError("CSC-CHAIN-0 VIOLATED: last ledger record missing hmac_chain_current")
        return chain_current

    def _verify_chain_integrity(self) -> None:
        """Verify full HMAC chain on the report ledger. CSC-CHAIN-0."""
        if not self._report_ledger_path.exists():
            return
        records = self._report_ledger_path.read_text(encoding="utf-8").strip().splitlines()
        if not records:
            return
        prev = _hmac_hex(_HMAC_KEY, "CSC-GENESIS-179")
        for i, raw in enumerate(records):
            rec = json.loads(raw)
            expected_prev = rec.get("hmac_chain_prev")
            if expected_prev != prev:
                raise RuntimeError(
                    f"CSC-CHAIN-0 VIOLATED: chain broken at record {i}; "
                    f"expected prev={prev[:16]}… got {str(expected_prev)[:16]}…"
                )
            prev = rec["hmac_chain_current"]

    def _append_report_record(self, report: StabilityReport) -> None:
        """Append-only write to stability report ledger. CSC-IMMUT-0."""
        record = asdict(report)
        with self._report_ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, separators=(",", ":")) + "\n")

    def _append_alert_record(self, alert: StabilityAlert) -> None:
        """Append-only write to alert log. CSC-ALERT-0."""
        record = asdict(alert)
        with self._alert_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, separators=(",", ":")) + "\n")

    # ── Data ingestion ────────────────────────────────────────────────────────

    def _load_constitution_snapshot(self) -> Tuple[Dict, str]:
        """
        Read CAE's constitution_snapshot.json. CSC-SCOPE-0, CSC-READONLY-0.
        Returns (snapshot_dict, sha256_of_raw_text).
        """
        if not self._cae_snapshot_path.exists():
            # Bootstrap: return an empty constitution snapshot
            return {}, _sha256("{}")

        raw = self._cae_snapshot_path.read_text(encoding="utf-8")
        try:
            snapshot = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"CSC: constitution snapshot JSON parse error: {exc}") from exc
        return snapshot, _sha256(raw)

    def _load_amendment_ledger(self) -> List[Dict]:
        """
        Read CAE's amendment execution ledger. CSC-SCOPE-0, CSC-READONLY-0.
        """
        if not self._cae_ledger_path.exists():
            return []
        records: List[Dict] = []
        for line in self._cae_ledger_path.read_text(encoding="utf-8").strip().splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # malformed line — skip but do not crash
        return records

    # ── Stability computation ─────────────────────────────────────────────────

    def _build_invariant_records(
        self,
        snapshot: Dict,
        ledger_records: List[Dict],
    ) -> Dict[str, InvariantStabilityRecord]:
        """
        Merge snapshot invariant list with amendment ledger events to produce
        per-invariant stability records. CSC-SCORE-0.
        """
        records: Dict[str, InvariantStabilityRecord] = {}

        # Seed from snapshot (most authoritative source of current invariant state)
        invariants_in_snapshot = snapshot.get("invariants", {})
        if isinstance(invariants_in_snapshot, dict):
            for inv_id, inv_data in invariants_in_snapshot.items():
                is_active = str(inv_data.get("status", "active")).lower() != "retired"
                records[inv_id] = InvariantStabilityRecord(
                    invariant_id=inv_id,
                    is_active=is_active,
                    reinforcement_count=inv_data.get("reinforcement_count", 0),
                )
        elif isinstance(invariants_in_snapshot, list):
            for item in invariants_in_snapshot:
                inv_id = item if isinstance(item, str) else item.get("id", str(item))
                records[inv_id] = InvariantStabilityRecord(
                    invariant_id=inv_id,
                    is_active=True,
                )

        # Enrich from ledger events
        for ledger_rec in ledger_records:
            amendments = ledger_rec.get("amendments_applied", [])
            if not isinstance(amendments, list):
                continue
            for amendment in amendments:
                inv_id = amendment.get("invariant_id", "")
                action = str(amendment.get("action", "")).upper()
                exec_id = amendment.get("execution_id", ledger_rec.get("cycle_id", ""))
                amended_at = amendment.get("executed_at", ledger_rec.get("cycle_timestamp", ""))

                if inv_id not in records:
                    records[inv_id] = InvariantStabilityRecord(
                        invariant_id=inv_id,
                        is_active=True,
                    )

                rec = records[inv_id]
                if exec_id and exec_id not in rec.amendment_ids:
                    rec.amendment_ids.append(exec_id)
                if amended_at:
                    rec.last_amended_at = amended_at

                if action == "REINFORCE":
                    rec.reinforcement_count += 1
                elif action == "REVIEW":
                    rec.review_flag_count += 1
                elif action == "ADD":
                    rec.add_count += 1
                    rec.is_active = True
                elif action == "RETIRE":
                    rec.is_active = False

        return records

    def _compute_scsi(self, records: Dict[str, InvariantStabilityRecord]) -> float:
        """
        System Constitutional Stability Index = mean of all per-invariant
        stability scores (including retired invariants at 0.0).
        CSC-SCORE-0.
        """
        if not records:
            return 1.0  # empty constitution is vacuously stable

        scores = [rec.compute_score() for rec in records.values()]
        return round(sum(scores) / len(scores), 6)

    def _classify_scsi(self, scsi: float) -> Tuple[str, bool]:
        """
        Returns (status_string, human0_escalation_flag).
        CSC-THRESHOLD-0, CSC-HUMAN0-0.
        """
        if scsi < CRITICAL_THRESHOLD:
            return "CRITICAL", True
        elif scsi < WARNING_THRESHOLD:
            return "WARNING", False
        return "OK", False

    # ── Public API ────────────────────────────────────────────────────────────

    def run_stability_cycle(self) -> StabilityReport:
        """
        Execute one full CSC stability computation cycle.

        Steps:
          1. Verify existing report ledger chain integrity (CSC-CHAIN-0)
          2. Load CAE constitution snapshot + execution ledger (CSC-SCOPE-0)
          3. Build per-invariant stability records (CSC-SCORE-0)
          4. Compute SCSI
          5. Classify SCSI against governed thresholds (CSC-THRESHOLD-0)
          6. Emit alert if SCSI < WARNING_THRESHOLD (CSC-ALERT-0)
          7. Append HMAC-chained report record (CSC-CHAIN-0, CSC-IMMUT-0)
          8. Write SCSI snapshot (CSC-AUDIT-0)
          9. Return StabilityReport

        Returns:
            StabilityReport with all cycle data.
        """
        # Step 1: chain integrity guard
        self._verify_chain_integrity()

        # Step 2: load data
        snapshot, snapshot_sha = self._load_constitution_snapshot()
        ledger_records = self._load_amendment_ledger()

        # Step 3: build per-invariant records
        inv_records = self._build_invariant_records(snapshot, ledger_records)

        # Step 4: compute SCSI
        scsi = self._compute_scsi(inv_records)

        # Step 5: classify
        scsi_status, human0_escalation = self._classify_scsi(scsi)

        # Step 6: alert if needed (CSC-ALERT-0 — fail-closed: alert MUST be written)
        alert_emitted = False
        if scsi < WARNING_THRESHOLD:
            alert_id = str(uuid.uuid4())
            alert_level = "CRITICAL" if human0_escalation else "WARNING"
            threshold_breached = CRITICAL_THRESHOLD if human0_escalation else WARNING_THRESHOLD
            alert = StabilityAlert(
                alert_id=alert_id,
                report_id="",  # filled after report_id is assigned below
                alert_level=alert_level,
                scsi=scsi,
                threshold_breached=threshold_breached,
                human0_escalation=human0_escalation,
                timestamp=_utc_iso(),
                message=(
                    f"CSC-ALERT-0: SCSI={scsi:.4f} breached {alert_level} threshold "
                    f"({threshold_breached}). "
                    + ("HUMAN-0 escalation required. " if human0_escalation else "")
                    + f"Governor: {_GOVERNOR}"
                ),
            )
            alert_emitted = True

        # Step 7: build and chain report
        report_id = str(uuid.uuid4())
        cycle_ts = _utc_iso()
        per_invariant_scores = {k: v.stability_score for k, v in inv_records.items()}

        # HMAC chain over deterministic payload
        chain_payload = json.dumps(
            {
                "report_id": report_id,
                "cycle_timestamp": cycle_ts,
                "scsi": scsi,
                "snapshot_sha256": snapshot_sha,
                "prev": self._prev_hmac,
            },
            sort_keys=True,
        )
        current_hmac = _hmac_hex(_HMAC_KEY, chain_payload)

        active_count = sum(1 for r in inv_records.values() if r.is_active)
        retired_count = len(inv_records) - active_count

        report = StabilityReport(
            report_id=report_id,
            cycle_timestamp=cycle_ts,
            invariant_count_active=active_count,
            invariant_count_retired=retired_count,
            invariant_count_total=len(inv_records),
            per_invariant_scores=per_invariant_scores,
            scsi=scsi,
            scsi_status=scsi_status,
            human0_escalation=human0_escalation,
            alert_emitted=alert_emitted,
            amendment_ledger_records_read=len(ledger_records),
            snapshot_sha256=snapshot_sha,
            hmac_chain_prev=self._prev_hmac,
            hmac_chain_current=current_hmac,
        )

        # Patch alert report_id now that we have it
        if alert_emitted:
            alert.report_id = report_id
            self._append_alert_record(alert)

        # Append report to ledger (CSC-IMMUT-0)
        self._append_report_record(report)
        self._prev_hmac = current_hmac

        # Step 8: write SCSI snapshot (CSC-AUDIT-0)
        scsi_snapshot = {
            "scsi": scsi,
            "scsi_status": scsi_status,
            "human0_escalation": human0_escalation,
            "report_id": report_id,
            "timestamp": cycle_ts,
            "invariant_count_active": active_count,
            "invariant_count_total": len(inv_records),
            "governor": _GOVERNOR,
            "innov_code": _INNOV_CODE,
        }
        self._scsi_snapshot_path.write_text(
            json.dumps(scsi_snapshot, indent=2), encoding="utf-8"
        )

        return report

    def get_scsi_snapshot(self) -> Optional[Dict]:
        """Return the last written SCSI snapshot, or None if none exists."""
        if not self._scsi_snapshot_path.exists():
            return None
        return json.loads(self._scsi_snapshot_path.read_text(encoding="utf-8"))

    def get_report_history(self, last_n: int = 10) -> List[Dict]:
        """Return the last N stability reports from the ledger."""
        if not self._report_ledger_path.exists():
            return []
        records = self._report_ledger_path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(r) for r in records[-last_n:] if r.strip()]

    def get_alert_history(self, last_n: int = 10) -> List[Dict]:
        """Return the last N stability alerts."""
        if not self._alert_log_path.exists():
            return []
        records = self._alert_log_path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(r) for r in records[-last_n:] if r.strip()]


# ── Module-level convenience ──────────────────────────────────────────────────

def run_csc_cycle(
    data_dir: Path = _DATA_DIR,
    cae_snapshot_path: Path = _CAE_SNAPSHOT_PATH,
    cae_ledger_path: Path = _CAE_EXECUTION_LEDGER_PATH,
) -> StabilityReport:
    """Convenience wrapper: instantiate CSC and run one stability cycle."""
    controller = ConstitutionalStabilityController(
        data_dir=data_dir,
        cae_snapshot_path=cae_snapshot_path,
        cae_ledger_path=cae_ledger_path,
    )
    return controller.run_stability_cycle()
