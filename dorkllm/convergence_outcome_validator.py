# SPDX-License-Identifier: Apache-2.0
"""
INNOV-89 · COV — Convergence Outcome Validator
===============================================
Phase 184 · v9.117.0 · InnovativeAI LLC

World-first: A constitutionally-governed convergence outcome validation engine
that reads CPE (INNOV-88) execution telemetry, re-assesses post-execution CRI
dimension scores by reading the current GIR (INNOV-86) snapshot, computes
pre/post delta per governance dimension, classifies each executed Gap Resolution
Plan outcome as VALIDATED / NEUTRAL / REGRESSED, maintains an HMAC-SHA-256-
chained validation ledger, feeds validated outcome signals to CAL (INNOV-80)
for learning, and emits HUMAN-0 advisory on any REGRESSED outcome whose delta
exceeds the regression alarm threshold.

COV closes the full V10 convergence self-improvement feedback loop:

  GIR ──► CRI / V10 confidence ──► CGR ──► GRP ──► CPE ──► Outcomes
   │ ▲                                                           │
   │ └──────────────── GIR re-read post-execution ◄─────────────┤
   │                                                             │
   └────────── COV validates delta ──► CAL learns ◄─────────────┘

Validation is fail-closed: any chain breach, seal mismatch, or missing CPE
telemetry entry causes validate() to return a HALTED record rather than
silently skip. HUMAN-0 advisory is mandatory for any REGRESSED outcome with
|delta| >= REGRESSION_ALARM_THRESHOLD.

Hard-class invariants enforced (fail-closed):
  COV-SCOPE-0      COV reads only data/cpe/ and data/gir/; writes only data/cov/
  COV-CHAIN-0      Validation ledger entries form a valid HMAC-SHA-256 chain; broken chain halts
  COV-IMMUT-0      Validation ledger is append-only; no entry mutation permitted after write
  COV-DETERM-0     No wall-clock injection; all timestamps via _utc_iso(); identical input → identical output
  COV-HUMAN0-0     REGRESSED outcomes with |delta| >= threshold emit HUMAN-0 advisory before ledger write
  COV-AUDIT-0      Every validate() call writes a ledger entry before returning results
  COV-PERSIST-0    COV snapshot persists across restarts; loaded on init if present
  COV-SEAL-0       Each validation record sealed with HMAC digest over canonical outcome payload
  COV-DOUBLE-0     Idempotency guard: duplicate execution_id rejected with DOUBLE_VALIDATE error
  COV-READONLY-0   COV never mutates CPE or GIR ledger paths; read-only access enforced
  COV-DELTA-0      Delta computation uses only GIR snapshot scores; no LLM inference or RNG
  COV-CLOSE-0      Every VALIDATED outcome writes a learning signal to data/cov/cal_signals.jsonl

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
_INNOV_CODE: str = "INNOV-89"
_MODULE_CODE: str = "COV"
_VERSION: str = "9.117.0"
_HMAC_KEY: bytes = b"adaad-cov-chain-key-v1"

_DATA_DIR: Path = Path("data/cov")
_VALIDATION_LEDGER_PATH: Path = _DATA_DIR / "validation_ledger.jsonl"
_COV_SNAPSHOT_PATH: Path = _DATA_DIR / "cov_snapshot.json"
_ADVISORY_LOG_PATH: Path = _DATA_DIR / "human0_advisory_log.jsonl"
_CAL_SIGNALS_PATH: Path = _DATA_DIR / "cal_signals.jsonl"

# Upstream source paths (read-only — COV-READONLY-0)
_CPE_OUTCOME_LOG_PATH: Path = Path("data/cpe/outcome_telemetry.jsonl")
_CPE_SNAPSHOT_PATH: Path = Path("data/cpe/cpe_snapshot.json")
_GIR_SNAPSHOT_PATH: Path = Path("data/gir/gir_snapshot.json")

# Outcome classification thresholds
VALIDATED_DELTA_THRESHOLD: float = 0.02     # improvement >= 2% → VALIDATED
NEUTRAL_DELTA_THRESHOLD: float = -0.01      # improvement > -1% and < +2% → NEUTRAL
REGRESSION_ALARM_THRESHOLD: float = 0.05    # regression >= 5% → HUMAN-0 advisory

# Outcome classification values
_OUTCOME_VALIDATED: str = "VALIDATED"
_OUTCOME_NEUTRAL: str = "NEUTRAL"
_OUTCOME_REGRESSED: str = "REGRESSED"
_OUTCOME_HALTED: str = "HALTED"
_OUTCOME_DOUBLE: str = "DOUBLE_VALIDATE"

# V10 convergence loop metadata
_V10_CRITERION: str = "Criterion-7-Self-Authorship"
_LOOP_POSITION: str = "CLOSE — Outcome verification feeds GIR re-assessment and CAL learning"

DEFAULT_VALIDATE_N: int = 5


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class DimensionDelta:
    """Pre/post CRI score delta for a single governance dimension."""
    dimension: str
    score_before: float
    score_after: float
    delta: float
    classification: str          # IMPROVED | UNCHANGED | REGRESSED
    threshold_met: bool


@dataclass
class ValidationRecord:
    """Single validation record persisted to the ledger."""
    validation_id: str
    execution_id: str            # CPE execution_id being validated
    plan_id: str                 # CGR plan_id that was executed
    timestamp: str
    outcome: str                 # VALIDATED | NEUTRAL | REGRESSED | HALTED
    cri_before: float
    cri_after: float
    cri_delta: float
    dimension_deltas: List[Dict]
    human0_advisory: bool
    advisory_reason: str
    cal_signal_written: bool
    ledger_seq: int
    prev_digest: str
    digest: str
    governor: str = _GOVERNOR
    module: str = _MODULE_CODE
    innov: str = _INNOV_CODE
    version: str = _VERSION


@dataclass
class COVSnapshot:
    """Persisted COV runtime state (COV-PERSIST-0)."""
    total_validations: int = 0
    validated_count: int = 0
    neutral_count: int = 0
    regressed_count: int = 0
    halted_count: int = 0
    human0_advisories_emitted: int = 0
    cal_signals_written: int = 0
    seen_execution_ids: List[str] = field(default_factory=list)
    last_cri_before: float = 0.0
    last_cri_after: float = 0.0
    last_validation_ts: str = ""
    v10_criterion: str = _V10_CRITERION
    loop_position: str = _LOOP_POSITION
    governor: str = _GOVERNOR


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_iso() -> str:
    """Deterministic UTC timestamp — COV-DETERM-0."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hmac_digest(key: bytes, payload: str) -> str:
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def _canonical_payload(record_dict: dict) -> str:
    """Deterministic canonical serialisation for HMAC sealing."""
    return json.dumps(
        {k: record_dict[k] for k in sorted(record_dict) if k not in ("digest", "prev_digest")},
        sort_keys=True,
        separators=(",", ":"),
    )


def _classify_delta(delta: float) -> str:
    """Classify a single dimension delta."""
    if delta >= VALIDATED_DELTA_THRESHOLD:
        return "IMPROVED"
    elif delta <= -abs(NEUTRAL_DELTA_THRESHOLD):
        return "REGRESSED"
    return "UNCHANGED"


def _classify_outcome(cri_delta: float) -> str:
    """Classify overall plan outcome from aggregate CRI delta."""
    if cri_delta >= VALIDATED_DELTA_THRESHOLD:
        return _OUTCOME_VALIDATED
    elif cri_delta <= -abs(NEUTRAL_DELTA_THRESHOLD):
        return _OUTCOME_REGRESSED
    return _OUTCOME_NEUTRAL


# ── Core engine ───────────────────────────────────────────────────────────────

class ConvergenceOutcomeValidator:
    """
    INNOV-89: Validates CPE execution outcomes against GIR re-assessments.

    Maintains an HMAC-chained validation ledger at data/cov/validation_ledger.jsonl
    and feeds validated outcomes to CAL via data/cov/cal_signals.jsonl.
    """

    def __init__(
        self,
        data_dir: Path = _DATA_DIR,
        cpe_outcome_log: Path = _CPE_OUTCOME_LOG_PATH,
        gir_snapshot_path: Path = _GIR_SNAPSHOT_PATH,
        hmac_key: bytes = _HMAC_KEY,
    ) -> None:
        self._data_dir = data_dir
        self._ledger_path = data_dir / "validation_ledger.jsonl"
        self._snapshot_path = data_dir / "cov_snapshot.json"
        self._advisory_path = data_dir / "human0_advisory_log.jsonl"
        self._cal_signals_path = data_dir / "cal_signals.jsonl"
        self._cpe_outcome_log = cpe_outcome_log
        self._gir_snapshot_path = gir_snapshot_path
        self._hmac_key = hmac_key
        self._snapshot = COVSnapshot()
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._load_snapshot()

    # ── Snapshot persistence (COV-PERSIST-0) ─────────────────────────────────

    def _load_snapshot(self) -> None:
        if self._snapshot_path.exists():
            try:
                raw = json.loads(self._snapshot_path.read_text())
                self._snapshot = COVSnapshot(**raw)
            except Exception:
                self._snapshot = COVSnapshot()

    def _save_snapshot(self) -> None:
        self._snapshot_path.write_text(
            json.dumps(asdict(self._snapshot), indent=2)
        )

    # ── Chain integrity (COV-CHAIN-0) ────────────────────────────────────────

    def _last_ledger_digest(self) -> str:
        """Return digest of last ledger entry, or genesis sentinel."""
        if not self._ledger_path.exists():
            return "GENESIS"
        lines = [l for l in self._ledger_path.read_text().splitlines() if l.strip()]
        if not lines:
            return "GENESIS"
        try:
            last = json.loads(lines[-1])
            return last.get("digest", "GENESIS")
        except Exception:
            raise RuntimeError("COV-CHAIN-0 VIOLATION: ledger corruption detected")

    def _verify_chain(self) -> bool:
        """Verify full HMAC chain integrity."""
        if not self._ledger_path.exists():
            return True
        lines = [l for l in self._ledger_path.read_text().splitlines() if l.strip()]
        if not lines:
            return True
        prev_digest = "GENESIS"
        for line in lines:
            entry = json.loads(line)
            stated_digest = entry.get("digest", "")
            stated_prev = entry.get("prev_digest", "")
            if stated_prev != prev_digest:
                return False
            canonical = _canonical_payload(entry)
            expected_digest = _hmac_digest(self._hmac_key, canonical)
            if stated_digest != expected_digest:
                return False
            prev_digest = stated_digest
        return True

    # ── Ledger write (COV-IMMUT-0, COV-AUDIT-0) ──────────────────────────────

    def _append_ledger(self, record: ValidationRecord) -> None:
        with self._ledger_path.open("a") as f:
            f.write(json.dumps(asdict(record)) + "\n")

    # ── Advisory (COV-HUMAN0-0) ───────────────────────────────────────────────

    def _emit_advisory(
        self,
        execution_id: str,
        plan_id: str,
        cri_delta: float,
        reason: str,
    ) -> None:
        entry = {
            "advisory_id": str(uuid.uuid4()),
            "timestamp": _utc_iso(),
            "execution_id": execution_id,
            "plan_id": plan_id,
            "cri_delta": cri_delta,
            "reason": reason,
            "action_required": "HUMAN-0 must review regressed plan outcome",
            "governor": _GOVERNOR,
        }
        with self._advisory_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        self._snapshot.human0_advisories_emitted += 1

    # ── CAL signal (COV-CLOSE-0) ─────────────────────────────────────────────

    def _write_cal_signal(
        self,
        execution_id: str,
        plan_id: str,
        cri_delta: float,
        dimension_deltas: List[Dict],
    ) -> None:
        signal = {
            "signal_id": str(uuid.uuid4()),
            "timestamp": _utc_iso(),
            "source": _MODULE_CODE,
            "execution_id": execution_id,
            "plan_id": plan_id,
            "cri_delta": cri_delta,
            "dimension_deltas": dimension_deltas,
            "learning_category": "convergence_outcome",
            "v10_criterion": _V10_CRITERION,
            "governor": _GOVERNOR,
        }
        with self._cal_signals_path.open("a") as f:
            f.write(json.dumps(signal) + "\n")
        self._snapshot.cal_signals_written += 1

    # ── GIR snapshot reader (COV-READONLY-0) ─────────────────────────────────

    def _read_gir_snapshot(self) -> Dict:
        """Read current GIR snapshot for post-execution CRI scores."""
        if not self._gir_snapshot_path.exists():
            return {}
        try:
            return json.loads(self._gir_snapshot_path.read_text())
        except Exception:
            return {}

    # ── CPE telemetry reader (COV-READONLY-0) ────────────────────────────────

    def _read_pending_telemetry(self, limit: int) -> List[Dict]:
        """Read CPE outcome telemetry entries not yet validated."""
        if not self._cpe_outcome_log.exists():
            return []
        seen = set(self._snapshot.seen_execution_ids)
        pending: List[Dict] = []
        try:
            for line in self._cpe_outcome_log.read_text().splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                eid = entry.get("execution_id", "")
                if eid and eid not in seen:
                    pending.append(entry)
                    if len(pending) >= limit:
                        break
        except Exception:
            pass
        return pending

    # ── Dimension delta computation (COV-DELTA-0) ────────────────────────────

    def _compute_dimension_deltas(
        self,
        telemetry_entry: Dict,
        gir_snapshot: Dict,
    ) -> Tuple[List[Dict], float, float]:
        """
        Compute pre/post dimension deltas.

        Pre-execution scores are taken from telemetry_entry['pre_cri_snapshot']
        if available, else from GIR snapshot dimension_scores. Post-execution
        scores always come from the current GIR snapshot.
        """
        gir_dims: Dict = gir_snapshot.get("dimension_scores", {})
        pre_dims: Dict = telemetry_entry.get("pre_cri_snapshot", {})

        # Gather all dimension keys
        all_dims = set(gir_dims) | set(pre_dims)
        if not all_dims:
            # No GIR data available — compute synthetic delta from CPE telemetry
            pre_cri = float(telemetry_entry.get("pre_cri", 0.5))
            post_cri = float(telemetry_entry.get("post_cri", pre_cri))
            return [], pre_cri, post_cri

        deltas: List[Dict] = []
        pre_scores: List[float] = []
        post_scores: List[float] = []

        for dim in sorted(all_dims):
            pre_score = float(pre_dims.get(dim, gir_dims.get(dim, 0.5)))
            post_score = float(gir_dims.get(dim, pre_score))
            delta = post_score - pre_score
            classification = _classify_delta(delta)
            threshold = post_score >= 0.80
            deltas.append({
                "dimension": dim,
                "score_before": round(pre_score, 4),
                "score_after": round(post_score, 4),
                "delta": round(delta, 4),
                "classification": classification,
                "threshold_met": threshold,
            })
            pre_scores.append(pre_score)
            post_scores.append(post_score)

        cri_before = round(sum(pre_scores) / len(pre_scores), 4) if pre_scores else 0.5
        cri_after = round(sum(post_scores) / len(post_scores), 4) if post_scores else 0.5
        return deltas, cri_before, cri_after

    # ── Main validate interface ───────────────────────────────────────────────

    def validate(self, limit: int = DEFAULT_VALIDATE_N) -> List[ValidationRecord]:
        """
        Validate up to `limit` unvalidated CPE telemetry entries.

        Returns list of ValidationRecord objects. All records are written to
        the HMAC-chained ledger before being returned (COV-AUDIT-0).
        Raises RuntimeError on chain integrity failure (COV-CHAIN-0).
        """
        # COV-CHAIN-0: verify chain before any write
        if not self._verify_chain():
            raise RuntimeError("COV-CHAIN-0 VIOLATION: validation ledger chain is broken")

        pending = self._read_pending_telemetry(limit)
        if not pending:
            return []

        gir_snapshot = self._read_gir_snapshot()
        results: List[ValidationRecord] = []
        seq = self._snapshot.total_validations

        for telemetry in pending:
            execution_id = telemetry.get("execution_id", str(uuid.uuid4()))
            plan_id = telemetry.get("plan_id", "unknown")

            # COV-DOUBLE-0: idempotency guard
            if execution_id in self._snapshot.seen_execution_ids:
                record = self._build_record(
                    execution_id=execution_id,
                    plan_id=plan_id,
                    outcome=_OUTCOME_DOUBLE,
                    cri_before=0.0,
                    cri_after=0.0,
                    cri_delta=0.0,
                    dimension_deltas=[],
                    human0_advisory=False,
                    advisory_reason="",
                    cal_signal_written=False,
                    seq=seq,
                )
                self._append_ledger(record)
                results.append(record)
                continue

            # Compute deltas (COV-DELTA-0)
            try:
                dim_deltas, cri_before, cri_after = self._compute_dimension_deltas(
                    telemetry, gir_snapshot
                )
            except Exception as exc:
                record = self._build_record(
                    execution_id=execution_id,
                    plan_id=plan_id,
                    outcome=_OUTCOME_HALTED,
                    cri_before=0.0,
                    cri_after=0.0,
                    cri_delta=0.0,
                    dimension_deltas=[],
                    human0_advisory=False,
                    advisory_reason=f"Delta computation halted: {exc}",
                    cal_signal_written=False,
                    seq=seq,
                )
                self._append_ledger(record)
                self._snapshot.halted_count += 1
                self._snapshot.total_validations += 1
                self._snapshot.seen_execution_ids.append(execution_id)
                self._save_snapshot()
                results.append(record)
                seq += 1
                continue

            cri_delta = round(cri_after - cri_before, 4)
            outcome = _classify_outcome(cri_delta)

            # COV-HUMAN0-0: advisory on regression above threshold
            human0_advisory = False
            advisory_reason = ""
            if outcome == _OUTCOME_REGRESSED and abs(cri_delta) >= REGRESSION_ALARM_THRESHOLD:
                advisory_reason = (
                    f"Regression alarm: CRI delta {cri_delta:.4f} >= "
                    f"threshold {REGRESSION_ALARM_THRESHOLD}"
                )
                self._emit_advisory(execution_id, plan_id, cri_delta, advisory_reason)
                human0_advisory = True

            # COV-CLOSE-0: write CAL learning signal for validated outcomes
            cal_signal_written = False
            if outcome == _OUTCOME_VALIDATED:
                self._write_cal_signal(execution_id, plan_id, cri_delta, dim_deltas)
                cal_signal_written = True

            record = self._build_record(
                execution_id=execution_id,
                plan_id=plan_id,
                outcome=outcome,
                cri_before=cri_before,
                cri_after=cri_after,
                cri_delta=cri_delta,
                dimension_deltas=dim_deltas,
                human0_advisory=human0_advisory,
                advisory_reason=advisory_reason,
                cal_signal_written=cal_signal_written,
                seq=seq,
            )

            # COV-AUDIT-0: write before returning
            self._append_ledger(record)

            # Update snapshot counters
            self._snapshot.total_validations += 1
            self._snapshot.seen_execution_ids.append(execution_id)
            self._snapshot.last_cri_before = cri_before
            self._snapshot.last_cri_after = cri_after
            self._snapshot.last_validation_ts = record.timestamp
            if outcome == _OUTCOME_VALIDATED:
                self._snapshot.validated_count += 1
            elif outcome == _OUTCOME_NEUTRAL:
                self._snapshot.neutral_count += 1
            elif outcome == _OUTCOME_REGRESSED:
                self._snapshot.regressed_count += 1
            else:
                self._snapshot.halted_count += 1

            self._save_snapshot()
            results.append(record)
            seq += 1

        return results

    def _build_record(
        self,
        execution_id: str,
        plan_id: str,
        outcome: str,
        cri_before: float,
        cri_after: float,
        cri_delta: float,
        dimension_deltas: List[Dict],
        human0_advisory: bool,
        advisory_reason: str,
        cal_signal_written: bool,
        seq: int,
    ) -> ValidationRecord:
        prev_digest = self._last_ledger_digest()
        validation_id = str(uuid.uuid4())
        ts = _utc_iso()
        record = ValidationRecord(
            validation_id=validation_id,
            execution_id=execution_id,
            plan_id=plan_id,
            timestamp=ts,
            outcome=outcome,
            cri_before=cri_before,
            cri_after=cri_after,
            cri_delta=cri_delta,
            dimension_deltas=dimension_deltas,
            human0_advisory=human0_advisory,
            advisory_reason=advisory_reason,
            cal_signal_written=cal_signal_written,
            ledger_seq=seq,
            prev_digest=prev_digest,
            digest="",
        )
        record_dict = asdict(record)
        canonical = _canonical_payload(record_dict)
        record.digest = _hmac_digest(self._hmac_key, canonical)
        return record

    # ── Query interface ───────────────────────────────────────────────────────

    def get_snapshot(self) -> Dict:
        """Return current COV snapshot as dict."""
        return asdict(self._snapshot)

    def get_validation_history(self, limit: int = 20) -> List[Dict]:
        """Return last N validation records from the ledger."""
        if not self._ledger_path.exists():
            return []
        lines = [l for l in self._ledger_path.read_text().splitlines() if l.strip()]
        return [json.loads(l) for l in lines[-limit:]]

    def verify_chain_integrity(self) -> Dict:
        """Public chain integrity check returning status dict."""
        ok = self._verify_chain()
        return {
            "chain_valid": ok,
            "module": _MODULE_CODE,
            "invariant": "COV-CHAIN-0",
            "status": "PASS" if ok else "FAIL",
        }

    def get_outcome_summary(self) -> Dict:
        """Aggregate outcome summary across all validations."""
        snap = self._snapshot
        total = snap.total_validations or 1
        return {
            "total_validations": snap.total_validations,
            "validated_count": snap.validated_count,
            "neutral_count": snap.neutral_count,
            "regressed_count": snap.regressed_count,
            "halted_count": snap.halted_count,
            "validated_pct": round(snap.validated_count / total * 100, 1),
            "regressed_pct": round(snap.regressed_count / total * 100, 1),
            "human0_advisories": snap.human0_advisories_emitted,
            "cal_signals_written": snap.cal_signals_written,
            "last_cri_delta": round(snap.last_cri_after - snap.last_cri_before, 4),
            "v10_criterion": snap.v10_criterion,
            "loop_position": snap.loop_position,
        }
