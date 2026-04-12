# SPDX-License-Identifier: Apache-2.0
"""FileTelemetrySink + TelemetryLedgerReader — Phase 21

Persistent, sha256-chained append-only telemetry sink for
routed_intelligence_decision.v1 events emitted by RoutedDecisionTelemetry.

Design:
- Follows the established ledger pattern (mutation_ledger.py,
  reviewer_reputation_ledger.py): append-only JSONL, sha256 hash chain,
  GENESIS_PREV_HASH sentinel, monotonically increasing sequence numbers.
- Emission failures are caught and logged; never propagated to the caller
  (preserves Phase 17 isolation contract).
- TelemetryLedgerReader is read-only; never writes to the file.
- FileTelemetrySink.verify_chain() is O(n) memory — streams line by line.
- InMemoryTelemetrySink (Phase 17) is not modified by this module.

Determinism guarantee: same payload sequence → identical record_hash chain.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

log = logging.getLogger(__name__)

# Matches mutation_ledger.py and reviewer_reputation_ledger.py
GENESIS_PREV_HASH: str = "sha256:" + ("0" * 64)

TELEMETRY_LEDGER_VERSION: str = "21.0"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TelemetryChainError(Exception):
    """Raised when a telemetry ledger fails sha256 chain verification.

    Attributes:
        sequence: The record sequence number at which verification failed.
        expected_hash: The hash that was expected (computed or stored prev).
        actual_hash: The hash that was found in the ledger.
    """

    def __init__(
        self,
        message: str,
        *,
        sequence: int = -1,
        expected_hash: str = "",
        actual_hash: str = "",
    ) -> None:
        super().__init__(message)
        self.sequence = sequence
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.sequence >= 0:
            parts.append(f"sequence={self.sequence}")
        if self.expected_hash:
            parts.append(f"expected={self.expected_hash[:20]}...")
        if self.actual_hash:
            parts.append(f"actual={self.actual_hash[:20]}...")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Record construction helpers
# ---------------------------------------------------------------------------


def _canonical_record_json(
    *, sequence: int, prev_hash: str, payload: dict[str, Any]
) -> str:
    """Deterministic JSON serialization of the hash-input fields.

    Same inputs → identical string → identical sha256.
    """
    return json.dumps(
        {"sequence": sequence, "prev_hash": prev_hash, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    )


def _compute_record_hash(
    *, sequence: int, prev_hash: str, payload: dict[str, Any]
) -> str:
    raw = _canonical_record_json(
        sequence=sequence, prev_hash=prev_hash, payload=payload
    )
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_full_record(
    *, sequence: int, prev_hash: str, payload: dict[str, Any]
) -> dict[str, Any]:
    record_hash = _compute_record_hash(
        sequence=sequence, prev_hash=prev_hash, payload=payload
    )
    return {
        "sequence": sequence,
        "prev_hash": prev_hash,
        "record_hash": record_hash,
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# Chain verification (shared by sink and reader)
# ---------------------------------------------------------------------------


def _verify_chain_from_lines(
    lines: Iterable[str], source_label: str = "ledger"
) -> bool:
    """Verify sha256 chain integrity over raw JSONL lines.

    Returns True on success.
    Raises TelemetryChainError on any violation.
    Never returns False silently.
    """
    prev_hash = GENESIS_PREV_HASH
    expected_seq = 0

    for lineno, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TelemetryChainError(
                f"{source_label}: JSON parse error at line {lineno}",
                sequence=lineno,
            ) from exc

        seq = record.get("sequence", -1)
        if seq != expected_seq:
            raise TelemetryChainError(
                f"{source_label}: sequence gap — expected {expected_seq}, got {seq}",
                sequence=seq,
            )

        stored_prev = record.get("prev_hash", "")
        if stored_prev != prev_hash:
            raise TelemetryChainError(
                f"{source_label}: prev_hash mismatch at sequence {seq}",
                sequence=seq,
                expected_hash=prev_hash,
                actual_hash=stored_prev,
            )

        payload = record.get("payload", {})
        computed = _compute_record_hash(
            sequence=seq, prev_hash=stored_prev, payload=payload
        )
        stored_hash = record.get("record_hash", "")
        if computed != stored_hash:
            raise TelemetryChainError(
                f"{source_label}: record_hash mismatch at sequence {seq}",
                sequence=seq,
                expected_hash=computed,
                actual_hash=stored_hash,
            )

        prev_hash = stored_hash
        expected_seq += 1

    return True


# ---------------------------------------------------------------------------
# FileTelemetrySink
# ---------------------------------------------------------------------------


class FileTelemetrySink:
    """Append-only, sha256-chained JSONL telemetry sink.

    Follows the ledger pattern established by mutation_ledger.py and
    reviewer_reputation_ledger.py.

    Emission failures are caught, logged at WARNING, and never propagated to
    the caller — preserving the Phase 17 isolation contract.

    Thread-safety: not guaranteed; callers in single-threaded contexts only.

    Args:
        path: JSONL ledger file path. Created (with parent dirs) if absent.
        chain_verify_on_open: If True (default) and the file exists, verify
            chain integrity before accepting any new emits. Chain violation
            raises TelemetryChainError at construction. Set False only in
            test contexts with explicit opt-out.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        chain_verify_on_open: bool = True,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing records to determine sequence and prev_hash
        self._sequence: int = 0
        self._prev_hash: str = GENESIS_PREV_HASH

        if self._path.exists() and self._path.stat().st_size > 0:
            existing_lines = self._path.read_text(encoding="utf-8").splitlines()
            if chain_verify_on_open:
                _verify_chain_from_lines(existing_lines, source_label=str(self._path))
            # Recover sequence and prev_hash from the last valid record
            for raw in reversed(existing_lines):
                stripped = raw.strip()
                if stripped:
                    try:
                        last = json.loads(stripped)
                        self._sequence = last["sequence"] + 1
                        self._prev_hash = last["record_hash"]
                    except (json.JSONDecodeError, KeyError):
                        pass
                    break

    # ------------------------------------------------------------------
    # Public interface (matches InMemoryTelemetrySink where applicable)
    # ------------------------------------------------------------------

    def emit(self, payload: dict[str, Any]) -> None:
        """Append a telemetry record to the JSONL ledger.

        Fail-isolated: any I/O or serialization error is caught and logged.
        Never raises.
        """
        try:
            record = _build_full_record(
                sequence=self._sequence,
                prev_hash=self._prev_hash,
                payload=payload,
            )
            line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line)
            self._prev_hash = record["record_hash"]
            self._sequence += 1
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "FileTelemetrySink.emit failed (path=%s): %s — telemetry suppressed",
                self._path,
                exc,
            )

    def verify_chain(self) -> bool:
        """Verify sha256 chain integrity of the entire ledger file.

        Returns True on success.
        Raises TelemetryChainError on any violation.
        Never returns False silently.
        """
        if not self._path.exists():
            return True
        lines = self._path.read_text(encoding="utf-8").splitlines()
        return _verify_chain_from_lines(lines, source_label=str(self._path))

    def entries(self) -> tuple[dict[str, Any], ...]:
        """Return all payload dicts in append order (sequence ascending).

        For memory-bounded use only. Large ledgers should use TelemetryLedgerReader.
        """
        if not self._path.exists():
            return ()
        payloads: list[dict[str, Any]] = []
        for raw in self._path.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if stripped:
                try:
                    record = json.loads(stripped)
                    payloads.append(record["payload"])
                except (json.JSONDecodeError, KeyError):
                    pass
        return tuple(payloads)

    def __len__(self) -> int:
        return self._sequence


# ---------------------------------------------------------------------------
# TelemetryLedgerReader
# ---------------------------------------------------------------------------


class TelemetryLedgerReader:
    """Read-only query interface for a FileTelemetrySink ledger.

    Does not write to the ledger file. Does not acquire write locks.
    All methods are deterministic: same ledger state + same params → identical result.

    Args:
        path: Path to the JSONL telemetry ledger file.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._memoized_snapshot: _LedgerSnapshot | None = None

    def _snapshot_key(self) -> tuple[int, int]:
        """Return deterministic cache key (size + mtime_ns) for ledger path."""
        stat = self._path.stat()
        return (stat.st_size, stat.st_mtime_ns)

    def iter_records(self) -> Iterator[dict[str, Any]]:
        """Yield parsed ledger records in append order without whole-file reads."""
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    yield json.loads(stripped)
                except json.JSONDecodeError:
                    continue

    def _records_snapshot(self) -> tuple[dict[str, Any], ...]:
        """Return memoized parsed records for the current file snapshot."""
        if not self._path.exists():
            self._memoized_snapshot = None
            return ()
        key = self._snapshot_key()
        if self._memoized_snapshot is not None and self._memoized_snapshot.key == key:
            return self._memoized_snapshot.records
        records = tuple(self.iter_records())
        self._memoized_snapshot = _LedgerSnapshot(key=key, records=records)
        return records

    def _all_records(self) -> list[dict[str, Any]]:
        """Return all parsed records in sequence order (ascending)."""
        return list(self._records_snapshot())

    def _all_payloads(self) -> list[dict[str, Any]]:
        return [r["payload"] for r in self._all_records() if "payload" in r]

    def payloads_chain_snapshot(self) -> tuple[list[dict[str, Any]], bool, int]:
        """Return payloads + chain status + record count in one file read.

        Returns:
            tuple(payloads, chain_valid, record_count)
            - payloads: parsed payload dicts in sequence order (ascending).
            - chain_valid: True only when the full chain validates.
            - record_count: number of non-empty lines successfully parsed as JSON.
        """
        if not self._path.exists():
            return ([], True, 0)

        payloads: list[dict[str, Any]] = []
        chain_valid = True
        record_count = 0

        prev_hash = GENESIS_PREV_HASH
        expected_seq = 0

        for raw_line in self._path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                record_count += 1
            except json.JSONDecodeError:
                chain_valid = False
                continue

            payload = record.get("payload")
            if isinstance(payload, dict):
                payloads.append(payload)

            if not chain_valid:
                continue

            seq = record.get("sequence", -1)
            stored_prev = record.get("prev_hash", "")
            stored_hash = record.get("record_hash", "")
            computed = _compute_record_hash(
                sequence=seq,
                prev_hash=stored_prev,
                payload=record.get("payload", {}),
            )

            if (
                seq != expected_seq
                or stored_prev != prev_hash
                or computed != stored_hash
            ):
                chain_valid = False
                continue

            prev_hash = stored_hash
            expected_seq += 1

        return (payloads, chain_valid, record_count)

    def query(
        self,
        *,
        strategy_id: str | None = None,
        outcome: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query telemetry payloads with optional filters, newest-first.

        Args:
            strategy_id: Filter to this strategy_id if provided.
            outcome: Filter to this outcome if provided.
            limit: Maximum number of results to return (max 500).
            offset: Number of matching results to skip (for pagination).

        Returns:
            List of payload dicts, newest-first (reverse sequence order).
        """
        if limit > 500:
            limit = 500
        if offset < 0:
            offset = 0
        if limit < 0:
            return []

        results: list[dict[str, Any]] = []
        matched = 0
        for record in reversed(self._records_snapshot()):
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            if strategy_id is not None and payload.get("strategy_id") != strategy_id:
                continue
            if outcome is not None and payload.get("outcome") != outcome:
                continue
            if matched < offset:
                matched += 1
                continue
            results.append(payload)
            if len(results) >= limit:
                break
        return results

    def win_rate_by_strategy(self) -> dict[str, float]:
        """Compute approval win rate per strategy_id.

        Returns:
            dict mapping strategy_id → approved_count / total_count.
            Returns {} on empty ledger.
            Returns 0.0 for strategies with zero approvals.
        """
        totals: dict[str, int] = {}
        wins: dict[str, int] = {}
        for record in self._records_snapshot():
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            sid = payload.get("strategy_id")
            if not sid:
                continue
            totals[sid] = totals.get(sid, 0) + 1
            if payload.get("outcome") == "approved":
                wins[sid] = wins.get(sid, 0) + 1
        if not totals:
            return {}
        return {
            sid: wins.get(sid, 0) / total
            for sid, total in sorted(totals.items())
        }

    def strategy_summary(self) -> dict[str, dict[str, int]]:
        """Compute per-strategy decision counts.

        Returns:
            dict mapping strategy_id → {"total": int, "approved": int,
            "rejected": int, "held": int}
        """
        summary: dict[str, dict[str, int]] = {}
        for record in self._records_snapshot():
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            sid = payload.get("strategy_id")
            if not sid:
                continue
            if sid not in summary:
                summary[sid] = {"total": 0, "approved": 0, "rejected": 0, "held": 0}
            outcome = payload.get("outcome", "")
            summary[sid]["total"] += 1
            if outcome == "approved":
                summary[sid]["approved"] += 1
            elif outcome == "rejected":
                summary[sid]["rejected"] += 1
            else:
                summary[sid]["held"] += 1
        return dict(sorted(summary.items()))

    def verify_chain(self) -> bool:
        """Verify sha256 chain integrity of the ledger.

        Returns True on success.
        Raises TelemetryChainError on any violation.
        Never returns False silently.
        """
        if not self._path.exists():
            return True
        with self._path.open("r", encoding="utf-8") as fh:
            return _verify_chain_from_lines(fh, source_label=str(self._path))

    def __len__(self) -> int:
        return len(self._records_snapshot())


@dataclass(frozen=True)
class _LedgerSnapshot:
    key: tuple[int, int]
    records: tuple[dict[str, Any], ...]
