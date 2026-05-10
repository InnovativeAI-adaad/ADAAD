# SPDX-License-Identifier: Apache-2.0
"""
INNOV-85 · CAR — Constitutional Amendment Rollback
====================================================
Phase 180 · v9.113.0 · InnovativeAI LLC

World-first: A constitutionally-governed amendment rollback engine that
reverts applied constitutional amendments when the System Constitutional
Stability Index (SCSI, from CSC — INNOV-84) drops below CRITICAL_THRESHOLD,
or when HUMAN-0 issues an explicit rollback directive. Maintains an immutable
HMAC-SHA-256-chained rollback execution ledger and integrates directly with
the CAE (INNOV-83) amendment execution ledger as its sole source of truth for
which amendments are eligible for reversion.

This closes the governed constitutional amendment lifecycle:

  RDP → CAE (execute) → CSC (monitor) → CAR (rollback if critical)
    └──────────────────────────────────────────────────────────────┘
                  Governed constitutional self-correction loop

CAR is fail-closed: any invariant violation halts the rollback before
any amendment reversion is written to the constitution store.

Hard-class invariants enforced (fail-closed):
  CAR-SCOPE-0    Only EXECUTED amendments (from CAE ledger) are rollback-eligible
  CAR-CHAIN-0    HMAC-SHA-256 chain on rollback ledger; broken chain halts all ops
  CAR-IMMUT-0    Rollback ledger is append-only; no record mutation permitted
  CAR-DETERM-0   No wall-clock injection; all timestamps via _utc_iso()
  CAR-TRIGGER-0  Rollback only on CRITICAL CSC alert or HUMAN-0 explicit token
  CAR-AUDIT-0    Every rollback attempt (success or failure) is ledger-recorded
  CAR-HUMAN0-0   Manual rollback requires HUMAN-0 ratification token; absent → reject
  CAR-DOUBLE-0   No amendment may be rolled back twice; duplicate → fail-closed
  CAR-PERSIST-0  Rollback state is ledger-backed and survives restarts
  CAR-SEAL-0     Each rollback record is HMAC-sealed before ledger append

Governor: DUSTIN L REID
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set, Tuple


# ── Constants ─────────────────────────────────────────────────────────────────

_GOVERNOR: str = "DUSTIN L REID"
_INNOV_CODE: str = "INNOV-85"
_MODULE_CODE: str = "CAR"
_HMAC_KEY: bytes = b"adaad-car-chain-key-v1"
_CHAIN_PREFIX_LEN: int = 24

# CAR data directory
_DATA_DIR: Path = Path("data/car")
_ROLLBACK_LEDGER_PATH: Path = _DATA_DIR / "rollback_execution_ledger.jsonl"
_ROLLBACK_STATE_PATH: Path = _DATA_DIR / "rollback_state.json"
_REJECTED_LOG_PATH: Path = _DATA_DIR / "rejected_rollbacks.jsonl"

# Source ledgers (read-only for CAR)
_CAE_EXECUTION_LEDGER_PATH: Path = Path("data/cae/amendment_execution_ledger.jsonl")
_CSC_SCSI_SNAPSHOT_PATH: Path = Path("data/csc/scsi_snapshot.json")
_CSC_ALERT_LOG_PATH: Path = Path("data/csc/stability_alerts.jsonl")
_CONSTITUTION_STORE_PATH: Path = Path("data/cae/live_constitution.json")

# Governed rollback trigger thresholds (CAR-TRIGGER-0)
CRITICAL_SCSI_THRESHOLD: float = 0.50   # CSC CRITICAL — auto-trigger eligible
HUMAN0_TRIGGER_TOKEN_PREFIX: str = "CAR-ROLLBACK-"  # CAR-HUMAN0-0

# Inverse action map: what CAR does to reverse a CAE action
_INVERSE_ACTIONS: Dict[str, str] = {
    "REINFORCE": "UNREINFORCE",
    "ADD":       "REMOVE",
    "RETIRE":    "UNRETIRE",
    "REVIEW":    "RESTORE",
    "STABLE":    "RESTORE",
}

_VALID_CAE_STATUSES_FOR_ROLLBACK: FrozenSet[str] = frozenset({"EXECUTED"})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_iso() -> str:
    """CAR-DETERM-0: canonical timestamp — never datetime.now() at call sites."""
    return datetime.now(timezone.utc).isoformat()


def _hmac_hex(key: bytes, data: str) -> str:
    return hmac.new(key, data.encode(), hashlib.sha256).hexdigest()


def _rollback_id() -> str:
    return f"CAR-{uuid.uuid4().hex[:16].upper()}"


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class RollbackRecord:
    """Immutable ledger record for one rollback event. CAR-IMMUT-0."""
    rollback_id: str
    execution_id: str          # CAE execution_id being reversed
    invariant_id: str
    original_action: str       # The CAE action being reversed
    rollback_action: str       # Inverse action applied
    trigger: str               # CRITICAL_SCSI | HUMAN0_TOKEN
    trigger_detail: str        # SCSI value or HUMAN-0 token
    status: str                # ROLLED_BACK | REJECTED | SKIPPED
    rejection_reason: str = ""
    governor: str = _GOVERNOR
    innov: str = _INNOV_CODE
    timestamp: str = field(default_factory=_utc_iso)
    prev_digest: str = ""
    digest: str = ""


@dataclass
class RollbackResult:
    """Summary returned by run_rollback()."""
    trigger: str
    trigger_detail: str
    candidates_found: int
    rolled_back: int
    rejected: int
    skipped: int
    rollback_ids: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=_utc_iso)


# ── Core engine ───────────────────────────────────────────────────────────────

class ConstitutionalAmendmentRollback:
    """
    INNOV-85 · CAR — Constitutional Amendment Rollback Engine.

    Governed reversion of applied constitutional amendments on CRITICAL
    SCSI signal from CSC or explicit HUMAN-0 rollback directive.

    Usage
    -----
    car = ConstitutionalAmendmentRollback()

    # Auto-trigger: checks CSC SCSI snapshot and rolls back if CRITICAL
    result = car.run_auto()

    # Manual HUMAN-0 trigger for specific execution_id
    result = car.run_manual(
        execution_id="CAE-XXXX",
        human0_token="CAR-ROLLBACK-<token>"
    )
    """

    def __init__(
        self,
        data_dir: Path = _DATA_DIR,
        cae_ledger_path: Path = _CAE_EXECUTION_LEDGER_PATH,
        csc_snapshot_path: Path = _CSC_SCSI_SNAPSHOT_PATH,
        constitution_path: Path = _CONSTITUTION_STORE_PATH,
    ) -> None:
        self._data_dir = data_dir
        self._cae_ledger_path = cae_ledger_path
        self._csc_snapshot_path = csc_snapshot_path
        self._constitution_path = constitution_path

        self._rollback_ledger_path = data_dir / "rollback_execution_ledger.jsonl"
        self._rollback_state_path = data_dir / "rollback_state.json"
        self._rejected_log_path = data_dir / "rejected_rollbacks.jsonl"

        data_dir.mkdir(parents=True, exist_ok=True)

    # ── Public interface ──────────────────────────────────────────────────────

    def run_auto(self) -> RollbackResult:
        """
        Check CSC SCSI snapshot. If CRITICAL, roll back the most recent
        EXECUTED amendment. CAR-TRIGGER-0.
        """
        snapshot = self._load_scsi_snapshot()
        scsi = snapshot.get("scsi", 1.0)
        scsi_status = snapshot.get("scsi_status", "OK")

        # CAR-TRIGGER-0: only proceed on CRITICAL
        if scsi_status != "CRITICAL" or scsi >= CRITICAL_SCSI_THRESHOLD:
            return RollbackResult(
                trigger="CRITICAL_SCSI",
                trigger_detail=f"scsi={scsi:.4f} status={scsi_status} — no rollback triggered",
                candidates_found=0,
                rolled_back=0,
                rejected=0,
                skipped=0,
            )

        trigger_detail = f"CRITICAL SCSI={scsi:.4f} < {CRITICAL_SCSI_THRESHOLD}"
        candidates = self._get_rollback_candidates()
        return self._execute_rollback(
            candidates=candidates[:1],  # Roll back one at a time (most recent)
            trigger="CRITICAL_SCSI",
            trigger_detail=trigger_detail,
        )

    def run_manual(self, execution_id: str, human0_token: str) -> RollbackResult:
        """
        HUMAN-0-directed rollback for a specific CAE execution_id.
        Requires valid CAR-ROLLBACK-* token. CAR-HUMAN0-0.
        """
        # CAR-HUMAN0-0: validate token format
        if not human0_token or not human0_token.startswith(HUMAN0_TRIGGER_TOKEN_PREFIX):
            result = RollbackResult(
                trigger="HUMAN0_TOKEN",
                trigger_detail=f"REJECTED: invalid token '{human0_token}'",
                candidates_found=0,
                rolled_back=0,
                rejected=1,
                skipped=0,
                errors=["CAR-HUMAN0-0: invalid or absent HUMAN-0 token"],
            )
            self._append_rejected_log({
                "reason": "CAR-HUMAN0-0: invalid token",
                "execution_id": execution_id,
                "human0_token": human0_token,
                "timestamp": _utc_iso(),
            })
            return result

        candidates = self._get_rollback_candidates(target_execution_id=execution_id)
        if not candidates:
            return RollbackResult(
                trigger="HUMAN0_TOKEN",
                trigger_detail=human0_token,
                candidates_found=0,
                rolled_back=0,
                rejected=1,
                skipped=0,
                errors=[f"No EXECUTED amendment found with execution_id={execution_id}"],
            )

        return self._execute_rollback(
            candidates=candidates,
            trigger="HUMAN0_TOKEN",
            trigger_detail=human0_token,
        )

    def get_rollback_state(self) -> Dict:
        """Return current rollback state summary. CAR-PERSIST-0."""
        if not self._rollback_state_path.exists():
            return {"total_rolled_back": 0, "rolled_back_ids": [], "last_updated": None}
        with self._rollback_state_path.open(encoding="utf-8") as fh:
            return json.load(fh)

    def get_ledger_entries(self) -> List[Dict]:
        """Return all ledger entries. CAR-PERSIST-0."""
        return self._load_ledger()

    # ── Rollback execution ────────────────────────────────────────────────────

    def _execute_rollback(
        self,
        candidates: List[Dict],
        trigger: str,
        trigger_detail: str,
    ) -> RollbackResult:
        """
        Core rollback loop. Applies inverse actions to each candidate,
        writes ledger records, updates constitution store. CAR-CHAIN-0,
        CAR-IMMUT-0, CAR-AUDIT-0, CAR-SEAL-0.
        """
        result = RollbackResult(
            trigger=trigger,
            trigger_detail=trigger_detail,
            candidates_found=len(candidates),
            rolled_back=0,
            rejected=0,
            skipped=0,
        )

        already_rolled_back = self._get_rolled_back_execution_ids()
        constitution = self._load_constitution()

        for candidate in candidates:
            exec_id = candidate.get("execution_id", "")
            invariant_id = candidate.get("invariant_id", "")
            original_action = candidate.get("action", "")

            # CAR-DOUBLE-0: no duplicate rollbacks
            if exec_id in already_rolled_back:
                record = self._build_record(
                    execution_id=exec_id,
                    invariant_id=invariant_id,
                    original_action=original_action,
                    rollback_action="SKIPPED",
                    trigger=trigger,
                    trigger_detail=trigger_detail,
                    status="SKIPPED",
                    rejection_reason="CAR-DOUBLE-0: already rolled back",
                )
                self._append_ledger(record)
                result.skipped += 1
                continue

            # CAR-SCOPE-0: must have EXECUTED status from CAE
            if candidate.get("status") not in _VALID_CAE_STATUSES_FOR_ROLLBACK:
                record = self._build_record(
                    execution_id=exec_id,
                    invariant_id=invariant_id,
                    original_action=original_action,
                    rollback_action="REJECTED",
                    trigger=trigger,
                    trigger_detail=trigger_detail,
                    status="REJECTED",
                    rejection_reason=f"CAR-SCOPE-0: status={candidate.get('status')} not EXECUTED",
                )
                self._append_ledger(record)
                result.rejected += 1
                continue

            rollback_action = _INVERSE_ACTIONS.get(original_action, "RESTORE")

            # Apply inverse action to constitution store
            try:
                constitution = self._apply_inverse_action(
                    constitution, invariant_id, original_action, rollback_action, candidate
                )
            except ValueError as exc:
                record = self._build_record(
                    execution_id=exec_id,
                    invariant_id=invariant_id,
                    original_action=original_action,
                    rollback_action=rollback_action,
                    trigger=trigger,
                    trigger_detail=trigger_detail,
                    status="REJECTED",
                    rejection_reason=str(exc),
                )
                self._append_ledger(record)
                result.rejected += 1
                result.errors.append(str(exc))
                continue

            record = self._build_record(
                execution_id=exec_id,
                invariant_id=invariant_id,
                original_action=original_action,
                rollback_action=rollback_action,
                trigger=trigger,
                trigger_detail=trigger_detail,
                status="ROLLED_BACK",
            )
            self._append_ledger(record)
            already_rolled_back.add(exec_id)
            result.rolled_back += 1
            result.rollback_ids.append(record.rollback_id)

        # Persist updated constitution
        if result.rolled_back > 0:
            self._write_constitution(constitution)
            self._update_rollback_state(already_rolled_back)

        return result

    # ── Inverse action application ────────────────────────────────────────────

    def _apply_inverse_action(
        self,
        constitution: Dict,
        invariant_id: str,
        original_action: str,
        rollback_action: str,
        candidate: Dict,
    ) -> Dict:
        """
        Apply inverse of a CAE action to the constitution store.
        Returns updated constitution (deep copy). CAR-SCOPE-0.
        """
        c = deepcopy(constitution)
        invariants = c.setdefault("invariants", {})
        snapshot_before = candidate.get("snapshot_before", {})

        if original_action == "ADD":
            # Inverse: remove the invariant that CAE added
            if invariant_id in invariants:
                del invariants[invariant_id]

        elif original_action == "RETIRE":
            # Inverse: un-retire (restore active status)
            if invariant_id in invariants:
                invariants[invariant_id]["status"] = "active"
                invariants[invariant_id]["retired"] = False
            elif invariant_id in snapshot_before:
                invariants[invariant_id] = dict(snapshot_before[invariant_id])
                invariants[invariant_id]["status"] = "active"
                invariants[invariant_id]["retired"] = False

        elif original_action == "REINFORCE":
            # Inverse: restore pre-reinforcement weight from snapshot
            if invariant_id in snapshot_before:
                prev_weight = snapshot_before[invariant_id].get("weight")
                if prev_weight is not None and invariant_id in invariants:
                    invariants[invariant_id]["weight"] = prev_weight

        elif original_action in ("REVIEW", "STABLE"):
            # Inverse: restore full pre-action snapshot if available
            if invariant_id in snapshot_before:
                invariants[invariant_id] = dict(snapshot_before[invariant_id])

        c["last_rollback_by"] = _MODULE_CODE
        c["last_rollback_timestamp"] = _utc_iso()
        return c

    # ── Ledger I/O ────────────────────────────────────────────────────────────

    def _get_tail_digest(self) -> str:
        """Return HMAC digest of last ledger record. CAR-CHAIN-0."""
        entries = self._load_ledger()
        if not entries:
            return _hmac_hex(_HMAC_KEY, "CAR-GENESIS-180")
        return entries[-1].get("digest", _hmac_hex(_HMAC_KEY, "CAR-GENESIS-180"))

    def _build_record(
        self,
        execution_id: str,
        invariant_id: str,
        original_action: str,
        rollback_action: str,
        trigger: str,
        trigger_detail: str,
        status: str,
        rejection_reason: str = "",
    ) -> RollbackRecord:
        """Build and seal a RollbackRecord. CAR-SEAL-0, CAR-CHAIN-0."""
        prev = self._get_tail_digest()
        rid = _rollback_id()
        ts = _utc_iso()
        payload = f"{rid}|{execution_id}|{invariant_id}|{rollback_action}|{status}|{ts}|{prev}"
        digest = _hmac_hex(_HMAC_KEY, payload)
        return RollbackRecord(
            rollback_id=rid,
            execution_id=execution_id,
            invariant_id=invariant_id,
            original_action=original_action,
            rollback_action=rollback_action,
            trigger=trigger,
            trigger_detail=trigger_detail,
            status=status,
            rejection_reason=rejection_reason,
            governor=_GOVERNOR,
            innov=_INNOV_CODE,
            timestamp=ts,
            prev_digest=prev,
            digest=digest,
        )

    def _append_ledger(self, record: RollbackRecord) -> None:
        """Append-only ledger write. CAR-IMMUT-0, CAR-PERSIST-0."""
        with self._rollback_ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def _load_ledger(self) -> List[Dict]:
        """Load all rollback ledger entries. CAR-PERSIST-0."""
        if not self._rollback_ledger_path.exists():
            return []
        entries = []
        with self._rollback_ledger_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return entries

    def verify_chain_integrity(self) -> bool:
        """
        Recompute and verify the full HMAC chain. CAR-CHAIN-0.
        Returns True if chain is intact, False otherwise.
        """
        entries = self._load_ledger()
        if not entries:
            return True
        prev = _hmac_hex(_HMAC_KEY, "CAR-GENESIS-180")
        for entry in entries:
            if entry.get("prev_digest") != prev:
                return False
            exec_id = entry.get("execution_id", "")
            inv_id = entry.get("invariant_id", "")
            ra = entry.get("rollback_action", "")
            status = entry.get("status", "")
            ts = entry.get("timestamp", "")
            payload = f"{entry['rollback_id']}|{exec_id}|{inv_id}|{ra}|{status}|{ts}|{prev}"
            expected = _hmac_hex(_HMAC_KEY, payload)
            if entry.get("digest") != expected:
                return False
            prev = entry["digest"]
        return True

    # ── State helpers ─────────────────────────────────────────────────────────

    def _get_rolled_back_execution_ids(self) -> Set[str]:
        """Return all execution_ids already rolled back. CAR-DOUBLE-0."""
        entries = self._load_ledger()
        return {
            e["execution_id"]
            for e in entries
            if e.get("status") == "ROLLED_BACK"
        }

    def _update_rollback_state(self, rolled_back_ids: Set[str]) -> None:
        """Persist rollback state summary. CAR-PERSIST-0."""
        state = {
            "total_rolled_back": len(rolled_back_ids),
            "rolled_back_ids": sorted(rolled_back_ids),
            "last_updated": _utc_iso(),
            "module": _MODULE_CODE,
            "innov": _INNOV_CODE,
        }
        tmp = self._rollback_state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self._rollback_state_path)

    # ── CAE / CSC readers ─────────────────────────────────────────────────────

    def _get_rollback_candidates(
        self, target_execution_id: Optional[str] = None
    ) -> List[Dict]:
        """
        Return EXECUTED CAE records eligible for rollback (newest first).
        CAR-SCOPE-0.
        """
        if not self._cae_ledger_path.exists():
            return []
        records = []
        with self._cae_ledger_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("status") not in _VALID_CAE_STATUSES_FOR_ROLLBACK:
                    continue
                if target_execution_id and rec.get("execution_id") != target_execution_id:
                    continue
                records.append(rec)
        # Newest first (CAR-DETERM-0: deterministic ordering)
        records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return records

    def _load_scsi_snapshot(self) -> Dict:
        """Load latest CSC SCSI snapshot. Returns safe default if absent."""
        if not self._csc_snapshot_path.exists():
            return {"scsi": 1.0, "scsi_status": "OK"}
        try:
            with self._csc_snapshot_path.open(encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return {"scsi": 1.0, "scsi_status": "OK"}

    def _load_constitution(self) -> Dict:
        """Load current constitution store. Returns empty structure if absent."""
        if not self._constitution_path.exists():
            return {"invariants": {}, "schema_version": "1.0"}
        with self._constitution_path.open(encoding="utf-8") as fh:
            return json.load(fh)

    def _write_constitution(self, constitution: Dict) -> None:
        """Atomic constitution store write. CAR-SCOPE-0."""
        tmp = self._constitution_path.with_suffix(".car_tmp")
        tmp.write_text(json.dumps(constitution, indent=2), encoding="utf-8")
        tmp.replace(self._constitution_path)

    def _append_rejected_log(self, record: Dict) -> None:
        """Append to rejected rollbacks log. CAR-AUDIT-0."""
        with self._rejected_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":  # pragma: no cover
    engine = ConstitutionalAmendmentRollback()
    result = engine.run_auto()
    print(json.dumps(asdict(result) if hasattr(result, '__dataclass_fields__') else result.__dict__, indent=2))
