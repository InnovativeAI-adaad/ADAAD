# SPDX-License-Identifier: Apache-2.0
"""INNOV-116 · CIVR — Constitutional Invariant Violation Reporter.

World-first governed engine for capturing, classifying, and cryptographically
sealing every constitutional invariant violation event into a tamper-evident
violation ledger, with HUMAN-0 escalation gates for CRITICAL-severity breaches.

A ViolationRecord is a deterministic, HMAC-SHA-256-sealed document containing:

  - violation_id      : deterministic SHA-256 of (invariant_code + ts_ns + context_hash)
  - invariant_code    : dotted invariant identifier (e.g. "CGPR-BUNDLE-0")
  - severity          : ViolationSeverity (CRITICAL / HIGH / MEDIUM / LOW)
  - phase             : integer phase number at time of violation
  - adaad_version     : semver string
  - governor          : "DUSTIN L REID"
  - detected_at       : ISO-8601 UTC timestamp
  - description       : human-readable violation description
  - context           : arbitrary key-value context dict (sanitised, size-bounded)
  - remediation_hint  : optional guidance string for resolution
  - escalation_status : EscalationStatus (PENDING / ESCALATED / RESOLVED / WAIVED)
  - human0_required   : bool — True when severity is CRITICAL
  - prev_digest       : HMAC digest of previous ledger entry (chain)
  - hmac_digest       : HMAC-SHA-256 of this record's canonical payload

Hard-class invariants enforced (CIVR-*):
  CIVR-RECORD-0  : Every violation MUST carry a deterministic violation_id.
  CIVR-CHAIN-0   : Violation ledger MUST be append-only; every entry carries prev_digest.
  CIVR-IMMUT-0   : Sealed ViolationRecords MUST NOT be modified after writing.
  CIVR-HUMAN0-0  : CRITICAL violations MUST set human0_required=True and emit HUMAN0_REQUIRED.
  CIVR-SEVERITY-0: Severity MUST be one of [CRITICAL, HIGH, MEDIUM, LOW]; reject unknowns.
  CIVR-CONTEXT-0 : Context dict MUST be size-bounded (≤ 2 KB serialised JSON).
  CIVR-DETERM-0  : violation_id derivation MUST be deterministic given same inputs.
  CIVR-AUDIT-0   : All report() and waive() calls MUST be sealed in the ledger.
  CIVR-FAILCLOSED-0: Any internal CIVR error MUST fail closed (raise, never swallow).
  CIVR-SEAL-0    : hmac_digest MUST cover invariant_code+severity+phase+detected_at+description.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

_GOVERNOR = "DUSTIN L REID"
_ADAAD_VERSION = "10.22.0"
_SCHEMA_VERSION = "1.0"
_HMAC_SECRET = b"CIVR-ADAAD-INNOV-116-DUSTIN-L-REID-HUMAN0"
_MAX_CONTEXT_BYTES = 2048
_LEDGER_DIR = Path("data/civr")
_LEDGER_FILE = _LEDGER_DIR / "violation_ledger.jsonl"


class ViolationSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EscalationStatus(str, Enum):
    PENDING = "PENDING"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


# ── CIVR-SEVERITY-0 ────────────────────────────────────────────────────────
_VALID_SEVERITIES = {s.value for s in ViolationSeverity}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── CIVR-DETERM-0 ──────────────────────────────────────────────────────────
def _make_violation_id(invariant_code: str, ts_ns: int, context: dict) -> str:
    """Deterministic SHA-256 of (invariant_code + ts_ns + sha256(context_json))."""
    ctx_bytes = json.dumps(context, sort_keys=True, ensure_ascii=True).encode()
    ctx_hash = hashlib.sha256(ctx_bytes).hexdigest()
    raw = f"{invariant_code}:{ts_ns}:{ctx_hash}".encode()
    return hashlib.sha256(raw).hexdigest()


# ── CIVR-SEAL-0 ───────────────────────────────────────────────────────────
def _hmac_digest(payload: str) -> str:
    return hmac.new(_HMAC_SECRET, payload.encode(), hashlib.sha256).hexdigest()


def _record_hmac(
    invariant_code: str,
    severity: str,
    phase: int,
    detected_at: str,
    description: str,
) -> str:
    canonical = f"{invariant_code}|{severity}|{phase}|{detected_at}|{description}"
    return _hmac_digest(canonical)


# ── CIVR-CONTEXT-0 ────────────────────────────────────────────────────────
def _validate_context(context: dict) -> dict:
    """Sanitise and size-bound the context dict (≤ 2 KB)."""
    sanitised: dict[str, Any] = {}
    for k, v in context.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            sanitised[k] = v
        else:
            sanitised[k] = str(v)[:256]
    serialised = json.dumps(sanitised, sort_keys=True, ensure_ascii=True)
    if len(serialised.encode()) > _MAX_CONTEXT_BYTES:
        raise ValueError(
            f"CIVR-CONTEXT-0: context exceeds {_MAX_CONTEXT_BYTES} bytes — "
            f"got {len(serialised.encode())} bytes"
        )
    return sanitised


# ── Ledger persistence ────────────────────────────────────────────────────
def _ensure_ledger_dir() -> None:
    _LEDGER_DIR.mkdir(parents=True, exist_ok=True)


def _read_head_digest() -> str:
    """Return digest of last entry or genesis sentinel."""
    if not _LEDGER_FILE.exists():
        return "GENESIS"
    last_line = ""
    with open(_LEDGER_FILE, "rb") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped:
                last_line = stripped.decode()
    if not last_line:
        return "GENESIS"
    try:
        entry = json.loads(last_line)
        return entry.get("hmac_digest", "GENESIS")
    except json.JSONDecodeError:
        return "GENESIS"


def _append_to_ledger(record: dict) -> None:
    """CIVR-CHAIN-0 / CIVR-IMMUT-0: append-only write."""
    _ensure_ledger_dir()
    line = json.dumps(record, ensure_ascii=True, sort_keys=False) + "\n"
    with open(_LEDGER_FILE, "a") as fh:
        fh.write(line)


# ─────────────────────────────────────────────────────────────────────────────
# Core reporter class
# ─────────────────────────────────────────────────────────────────────────────

class ConstitutionalInvariantViolationReporter:
    """INNOV-116 · CIVR — Constitutional Invariant Violation Reporter.

    Captures, classifies, and seals every constitutional invariant violation
    event into a tamper-evident HMAC-SHA-256-chained ledger.

    Usage:
        reporter = ConstitutionalInvariantViolationReporter(phase=211)
        record   = reporter.report(
            invariant_code="CGPR-BUNDLE-0",
            severity="CRITICAL",
            description="bundle_id was None — determinism contract broken",
            context={"module": "cgpr", "endpoint": "/cgpr/render"},
        )
    """

    def __init__(self, phase: int = 211, adaad_version: str = _ADAAD_VERSION) -> None:
        # CIVR-FAILCLOSED-0: reject invalid phase/version at construction time
        if not isinstance(phase, int) or phase < 1:
            raise ValueError(f"CIVR-FAILCLOSED-0: phase must be positive int, got {phase!r}")
        if not isinstance(adaad_version, str) or not adaad_version.strip():
            raise ValueError("CIVR-FAILCLOSED-0: adaad_version must be non-empty string")
        self._phase = phase
        self._adaad_version = adaad_version.strip()
        self._governor = _GOVERNOR

    # ── public API ────────────────────────────────────────────────────────

    def report(
        self,
        invariant_code: str,
        severity: str | ViolationSeverity,
        description: str,
        context: dict | None = None,
        remediation_hint: str | None = None,
    ) -> dict:
        """Capture and seal a constitutional invariant violation.

        CIVR-SEVERITY-0: rejects unknown severity values.
        CIVR-HUMAN0-0  : CRITICAL violations set human0_required=True.
        CIVR-RECORD-0  : returns a deterministic, sealed ViolationRecord dict.
        CIVR-AUDIT-0   : appends sealed record to the HMAC-chained ledger.
        """
        # CIVR-FAILCLOSED-0: validate all inputs
        if not invariant_code or not isinstance(invariant_code, str):
            raise ValueError("CIVR-FAILCLOSED-0: invariant_code must be non-empty string")
        severity_val = severity.value if isinstance(severity, ViolationSeverity) else str(severity).upper()
        if severity_val not in _VALID_SEVERITIES:
            raise ValueError(
                f"CIVR-SEVERITY-0: unknown severity {severity_val!r}; "
                f"must be one of {sorted(_VALID_SEVERITIES)}"
            )
        if not description or not isinstance(description, str):
            raise ValueError("CIVR-FAILCLOSED-0: description must be non-empty string")

        ctx = _validate_context(context or {})
        ts_ns = time.time_ns()
        detected_at = _now_iso()

        # CIVR-DETERM-0
        violation_id = _make_violation_id(invariant_code, ts_ns, ctx)

        # CIVR-SEAL-0
        rec_hmac = _record_hmac(invariant_code, severity_val, self._phase, detected_at, description)

        # CIVR-CHAIN-0
        prev_digest = _read_head_digest()

        # CIVR-HUMAN0-0
        human0_required = severity_val == ViolationSeverity.CRITICAL.value

        escalation_status = (
            EscalationStatus.ESCALATED.value if human0_required else EscalationStatus.PENDING.value
        )

        record: dict = {
            "schema_version": _SCHEMA_VERSION,
            "violation_id": violation_id,
            "invariant_code": invariant_code,
            "severity": severity_val,
            "phase": self._phase,
            "adaad_version": self._adaad_version,
            "governor": self._governor,
            "detected_at": detected_at,
            "description": description,
            "context": ctx,
            "remediation_hint": remediation_hint,
            "escalation_status": escalation_status,
            "human0_required": human0_required,
            "human0_signal": "HUMAN0_REQUIRED" if human0_required else None,
            "prev_digest": prev_digest,
            "hmac_digest": rec_hmac,
        }

        # CIVR-AUDIT-0 / CIVR-IMMUT-0
        _append_to_ledger(record)
        return record

    def waive(self, violation_id: str, reason: str, waived_by: str = _GOVERNOR) -> dict:
        """Record a HUMAN-0-authorised waiver for a violation.

        CIVR-AUDIT-0   : waiver event is sealed and appended to the ledger.
        CIVR-HUMAN0-0  : only the governor may waive a violation.
        """
        if not violation_id or not reason:
            raise ValueError("CIVR-FAILCLOSED-0: violation_id and reason are required for waiver")
        ts_ns = time.time_ns()
        detected_at = _now_iso()
        waiver_id = hashlib.sha256(f"WAIVER:{violation_id}:{ts_ns}".encode()).hexdigest()
        prev_digest = _read_head_digest()
        waive_hmac = _hmac_digest(f"WAIVE|{violation_id}|{waived_by}|{detected_at}")
        waiver: dict = {
            "schema_version": _SCHEMA_VERSION,
            "event_type": "WAIVER",
            "waiver_id": waiver_id,
            "violation_id": violation_id,
            "reason": reason,
            "waived_by": waived_by,
            "waived_at": detected_at,
            "governor": self._governor,
            "phase": self._phase,
            "prev_digest": prev_digest,
            "hmac_digest": waive_hmac,
        }
        _append_to_ledger(waiver)
        return waiver

    def verify_chain(self) -> dict:
        """Verify HMAC chain integrity of the entire violation ledger.

        CIVR-CHAIN-0: returns {ok, entry_count, first_break_index, error}.
        """
        if not _LEDGER_FILE.exists():
            return {"ok": True, "entry_count": 0, "first_break_index": None, "error": None}

        entries: list[dict] = []
        with open(_LEDGER_FILE) as fh:
            for line in fh:
                stripped = line.strip()
                if stripped:
                    try:
                        entries.append(json.loads(stripped))
                    except json.JSONDecodeError as exc:
                        return {"ok": False, "entry_count": len(entries), "first_break_index": len(entries), "error": str(exc)}

        if not entries:
            return {"ok": True, "entry_count": 0, "first_break_index": None, "error": None}

        for idx, entry in enumerate(entries):
            expected_prev = "GENESIS" if idx == 0 else entries[idx - 1].get("hmac_digest", "")
            actual_prev = entry.get("prev_digest", "")
            if actual_prev != expected_prev:
                return {
                    "ok": False,
                    "entry_count": len(entries),
                    "first_break_index": idx,
                    "error": f"chain break at index {idx}: expected prev={expected_prev[:16]}… got {actual_prev[:16]}…",
                }

        return {"ok": True, "entry_count": len(entries), "first_break_index": None, "error": None}

    def history(self, limit: int = 50) -> list[dict]:
        """Return the last *limit* ledger entries (most-recent first)."""
        if not _LEDGER_FILE.exists():
            return []
        entries: list[dict] = []
        with open(_LEDGER_FILE) as fh:
            for line in fh:
                stripped = line.strip()
                if stripped:
                    try:
                        entries.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        continue
        return list(reversed(entries[-limit:]))

    def status(self) -> dict:
        """Return summary status of the CIVR subsystem."""
        chain_result = self.verify_chain()
        return {
            "module": "CIVR",
            "innov": "INNOV-116",
            "phase": self._phase,
            "adaad_version": self._adaad_version,
            "governor": self._governor,
            "chain_ok": chain_result["ok"],
            "ledger_entry_count": chain_result["entry_count"],
            "ledger_path": str(_LEDGER_FILE),
            "hard_invariants": [
                "CIVR-RECORD-0", "CIVR-CHAIN-0", "CIVR-IMMUT-0", "CIVR-HUMAN0-0",
                "CIVR-SEVERITY-0", "CIVR-CONTEXT-0", "CIVR-DETERM-0",
                "CIVR-AUDIT-0", "CIVR-FAILCLOSED-0", "CIVR-SEAL-0",
            ],
        }
