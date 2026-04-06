# SPDX-License-Identifier: Apache-2.0
"""GateDecisionLedger + GateDecisionReader — ADAAD Phase 35.

SHA-256 hash-chained append-only JSONL audit ledger for
``GovernanceGate.approve_mutation()`` outcomes.  Closes the gate-decision
observability gap: every approve/reject outcome is now persisted in a
tamper-evident chain, and the gate approval rate feeds into the composite
governance health score ``h`` as the 9th signal (``gate_approval_rate_score``,
weight 0.05).

Architectural pattern mirrors CertifierScanLedger (Phase 33) and
ThreatScanLedger (Phase 30):
- GENESIS_PREV_HASH sentinel: ``"sha256:" + "0" * 64``
- Monotonically increasing sequence numbers
- Each record linked to predecessor via prev_hash → record_hash chain
- ``chain_verify_on_open=True`` raises ``GateDecisionChainError`` on
  construction if chain integrity is violated
- ``emit()`` catches ALL failures; logs WARNING; never propagates
- Reader is strictly read-only; no write path

Design invariants
─────────────────
- Append-only: no record is ever overwritten or deleted.
- Fail-closed chain verification: any hash mismatch → ``GateDecisionChainError``.
- Emit failure isolation: I/O errors in ``emit()`` never surface to callers.
- Deterministic replay: same decision sequence → same chain hashes.
- Timestamp excluded from ``record_hash`` — chain is wall-clock independent.
- Ledger inactive by default: no ``path`` kwarg → no file written.
- GovernanceGate isolation: this module never imports GovernanceGate;
  it only consumes ``GateDecision.to_payload()`` dicts.
- Advisory only: ``GateDecisionLedger`` records outcomes; it never
  approves or blocks mutations.  GovernanceGate retains sole authority.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

GATE_DECISION_LEDGER_GENESIS_PREV_HASH: str = "sha256:" + "0" * 64
GATE_DECISION_LEDGER_VERSION: str = "35.0"

DEFAULT_GATE_DECISION_LEDGER_PATH: str = "security/ledger/gate_decision_audit.jsonl"

VALID_DECISIONS = frozenset({"pass", "deny", "override_pass", "parallel_pass"})


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class GateDecisionChainError(RuntimeError):
    """Raised when GateDecisionLedger chain verification fails."""

    def __init__(self, message: str, *, sequence: int, detail: str) -> None:
        super().__init__(message)
        self.sequence = sequence
        self.detail = detail


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sha256_prefixed(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def _build_gate_record(
    *,
    sequence: int,
    prev_hash: str,
    decision_payload: dict[str, Any],
    timestamp_iso: str,
) -> dict[str, Any]:
    """Build a JSONL record from a ``GateDecision.to_payload()`` dict.

    ``timestamp_iso`` is stored as metadata but excluded from ``record_hash``
    so the chain is deterministic regardless of wall-clock time.

    Expected ``decision_payload`` keys (all optional — safe defaults apply):
        approved, decision, mutation_id, trust_mode, reason_codes,
        failed_rules, human_override, decision_id, gate_mode.
    """
    approved = bool(decision_payload.get("approved", False))
    decision = str(decision_payload.get("decision") or "deny")
    failed_rules = list(decision_payload.get("failed_rules") or [])
    reason_codes = list(decision_payload.get("reason_codes") or [])

    chained: dict[str, Any] = {
        "ledger_version":  GATE_DECISION_LEDGER_VERSION,
        "sequence":        sequence,
        "prev_hash":       prev_hash,
        "approved":        approved,
        "decision":        decision if decision in VALID_DECISIONS else "deny",
        "mutation_id":     str(decision_payload.get("mutation_id") or ""),
        "trust_mode":      str(decision_payload.get("trust_mode") or "standard"),
        "failed_rule_count": len(failed_rules),
        "reason_code_count": len(reason_codes),
        "human_override":  bool(decision_payload.get("human_override", False)),
        "gate_mode":       str(decision_payload.get("gate_mode") or "serial"),
        "decision_id":     str(decision_payload.get("decision_id") or ""),
    }

    record_hash = _sha256_prefixed(_canonical_bytes(chained))
    return {
        **chained,
        "record_hash": record_hash,
        "timestamp":   timestamp_iso,
        # Store full reason codes and failed rules for Reader analytics
        "failed_rules": failed_rules,
        "reason_codes": reason_codes,
    }


def _verify_chain_records(records: list[dict[str, Any]]) -> tuple[bool, int, str]:
    """Verify the hash chain.  Returns (ok, fail_sequence, detail)."""
    prev_hash = GATE_DECISION_LEDGER_GENESIS_PREV_HASH
    for rec in records:
        seq = int(rec.get("sequence", -1))
        if rec.get("prev_hash") != prev_hash:
            return False, seq, f"prev_hash mismatch at seq {seq}"
        chained_fields = {
            k: rec[k]
            for k in [
                "ledger_version", "sequence", "prev_hash", "approved", "decision",
                "mutation_id", "trust_mode", "failed_rule_count", "reason_code_count",
                "human_override", "gate_mode", "decision_id",
            ]
            if k in rec
        }
        expected = _sha256_prefixed(_canonical_bytes(chained_fields))
        if rec.get("record_hash") != expected:
            return False, seq, f"record_hash mismatch at seq {seq}"
        prev_hash = rec["record_hash"]
    return True, -1, ""


# ---------------------------------------------------------------------------
# GateDecisionLedger (writer)
# ---------------------------------------------------------------------------


class GateDecisionLedger:
    """Append-only SHA-256 hash-chained JSONL ledger for GovernanceGate decisions.

    Parameters
    ----------
    path:
        File path for the JSONL ledger.  ``None`` → inactive (no file written).
    chain_verify_on_open:
        When ``True`` (default), verify the existing chain on construction.
        Raises ``GateDecisionChainError`` on any integrity violation.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        chain_verify_on_open: bool = True,
    ) -> None:
        self._path: Path | None = Path(path) if path is not None else None
        self._sequence: int = 0
        self._prev_hash: str = GATE_DECISION_LEDGER_GENESIS_PREV_HASH

        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if self._path.exists():
                existing = self._load_records()
                if chain_verify_on_open and existing:
                    ok, fail_seq, detail = _verify_chain_records(existing)
                    if not ok:
                        raise GateDecisionChainError(
                            "GateDecisionLedger: chain integrity violation",
                            sequence=fail_seq,
                            detail=detail,
                        )
                if existing:
                    last = existing[-1]
                    self._sequence = int(last["sequence"]) + 1
                    self._prev_hash = last["record_hash"]

    def emit(self, decision_payload: dict[str, Any]) -> None:
        """Append a GateDecision payload to the ledger.

        Failure-isolated: any I/O or serialisation error is logged and
        swallowed.  Callers are never interrupted.

        Parameters
        ----------
        decision_payload:
            The dict returned by ``GateDecision.to_payload()``, or any dict
            with the expected keys (approved, decision, mutation_id, …).
        """
        if self._path is None:
            return
        try:
            timestamp_iso = datetime.now(timezone.utc).isoformat()
            record = _build_gate_record(
                sequence=self._sequence,
                prev_hash=self._prev_hash,
                decision_payload=decision_payload,
                timestamp_iso=timestamp_iso,
            )
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, separators=(",", ":")) + "\n")
            self._prev_hash = record["record_hash"]
            self._sequence += 1
        except Exception as exc:
            log.warning("GateDecisionLedger.emit() failed (swallowed): %s", exc)

    def verify_chain(self) -> bool:
        """Verify the current on-disk chain.  Returns ``True`` if intact."""
        if self._path is None or not self._path.exists():
            return True
        try:
            ok, _, _ = _verify_chain_records(self._load_records())
            return ok
        except Exception:
            return False

    def _load_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records


# ---------------------------------------------------------------------------
# GateDecisionReader (read-only analytics)
# ---------------------------------------------------------------------------


class GateDecisionReader:
    """Read-only analytics over a ``GateDecisionLedger`` JSONL file.

    Parameters
    ----------
    path:
        Path to the JSONL ledger.  A non-existent path is treated as empty.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._cache_key: tuple[int, int, int] | None = None
        self._cached_records: list[dict[str, Any]] | None = None
        self._cached_aggregates: dict[str, Any] | None = None

    def _file_cache_key(self) -> tuple[int, int, int] | None:
        if not self._path.exists():
            return None
        stat = self._path.stat()
        return (int(stat.st_ino), int(stat.st_mtime_ns), int(stat.st_size))

    @staticmethod
    def _compute_aggregates(records: list[dict[str, Any]]) -> dict[str, Any]:
        approved_count = 0
        decision_breakdown: dict[str, int] = {}
        failed_rules_frequency: dict[str, int] = {}
        trust_mode_breakdown: dict[str, int] = {}
        human_override_count = 0
        for rec in records:
            if rec.get("approved", False):
                approved_count += 1
            decision_label = str(rec.get("decision") or "deny")
            decision_breakdown[decision_label] = decision_breakdown.get(decision_label, 0) + 1
            trust_mode_label = str(rec.get("trust_mode") or "standard")
            trust_mode_breakdown[trust_mode_label] = trust_mode_breakdown.get(trust_mode_label, 0) + 1
            if rec.get("human_override", False):
                human_override_count += 1
            for rule_id in rec.get("failed_rules") or []:
                rule_id_s = str(rule_id)
                failed_rules_frequency[rule_id_s] = failed_rules_frequency.get(rule_id_s, 0) + 1

        total = len(records)
        approval_rate = 1.0 if total == 0 else round(approved_count / total, 6)
        return {
            "approval_rate": approval_rate,
            "rejection_rate": round(1.0 - approval_rate, 6),
            "human_override_count": human_override_count,
            "decision_breakdown": decision_breakdown,
            "failed_rules_frequency": failed_rules_frequency,
            "trust_mode_breakdown": trust_mode_breakdown,
        }

    def _records_and_aggregates(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        cache_key = self._file_cache_key()
        if (
            self._cache_key == cache_key
            and self._cached_records is not None
            and self._cached_aggregates is not None
        ):
            return self._cached_records, self._cached_aggregates

        if cache_key is None:
            records: list[dict[str, Any]] = []
        else:
            records = []
            with self._path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        aggregates = self._compute_aggregates(records)
        self._cache_key = cache_key
        self._cached_records = records
        self._cached_aggregates = aggregates
        return records, aggregates

    def _records(self) -> list[dict[str, Any]]:
        records, _ = self._records_and_aggregates()
        return records

    def history(
        self,
        *,
        limit: int | None = None,
        denied_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Return decision records, optionally filtered.

        Parameters
        ----------
        limit:
            Maximum number of records to return (most recent last).
        denied_only:
            When ``True``, return only denied (not approved) decisions.
        """
        recs = self._records()
        if denied_only:
            recs = [r for r in recs if not r.get("approved", True)]
        if limit is not None:
            recs = recs[-limit:]
        return recs

    def approval_rate(self) -> float:
        """Fraction of gate decisions that were approved.

        Returns ``1.0`` on empty history (no denials → healthy).
        """
        _, aggregates = self._records_and_aggregates()
        return float(aggregates["approval_rate"])

    def rejection_rate(self) -> float:
        """Fraction of gate decisions that were denied (1.0 - approval_rate)."""
        _, aggregates = self._records_and_aggregates()
        return float(aggregates["rejection_rate"])

    def decision_breakdown(self) -> dict[str, int]:
        """Count decisions by decision label (pass / deny / override_pass / …)."""
        _, aggregates = self._records_and_aggregates()
        return dict(aggregates["decision_breakdown"])

    def failed_rules_frequency(self) -> dict[str, int]:
        """Count how many times each rule_id appears in failed_rules."""
        _, aggregates = self._records_and_aggregates()
        return dict(aggregates["failed_rules_frequency"])

    def human_override_count(self) -> int:
        """Number of decisions where human_override=True."""
        _, aggregates = self._records_and_aggregates()
        return int(aggregates["human_override_count"])

    def trust_mode_breakdown(self) -> dict[str, int]:
        """Count decisions by trust_mode label."""
        _, aggregates = self._records_and_aggregates()
        return dict(aggregates["trust_mode_breakdown"])

    def common_aggregates(self) -> dict[str, Any]:
        """Return a snapshot of common aggregate metrics in one pass."""
        _, aggregates = self._records_and_aggregates()
        return {
            "approval_rate": float(aggregates["approval_rate"]),
            "rejection_rate": float(aggregates["rejection_rate"]),
            "human_override_count": int(aggregates["human_override_count"]),
            "decision_breakdown": dict(aggregates["decision_breakdown"]),
            "failed_rules_frequency": dict(aggregates["failed_rules_frequency"]),
            "trust_mode_breakdown": dict(aggregates["trust_mode_breakdown"]),
        }

    def verify_chain(self) -> bool:
        """Verify the on-disk hash chain.  Returns True if intact."""
        try:
            ok, _, _ = _verify_chain_records(self._records())
            return ok
        except Exception:
            return False


__all__ = [
    "GateDecisionChainError",
    "GateDecisionLedger",
    "GateDecisionReader",
    "GATE_DECISION_LEDGER_VERSION",
    "DEFAULT_GATE_DECISION_LEDGER_PATH",
]
