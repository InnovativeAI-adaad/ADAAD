# SPDX-License-Identifier: Apache-2.0
"""Phase 71 — Oracle Answer Persistence Ledger.

Appends every oracle answer to an append-only JSONL file so that past
queries can be replayed deterministically and audited.

Constitutional invariants
=========================
ORACLE-PERSIST-0   Every successful oracle query writes exactly one record to
                   the ledger before the HTTP response is returned.  Write
                   failures are logged as WARNING but never raise to the caller.
ORACLE-REPLAY-0    Records are newline-delimited JSON (JSONL); the file is
                   append-only and must not be modified after write.
ORACLE-DETERM-0    Two identical (query, event_window_hash) pairs produce
                   identical answer JSON, making replay verifiable.

Ledger record schema (v1)
=========================
{
  "schema_version": "71.1",
  "ts":             ISO-8601 UTC,
  "query":          str,
  "normalized_query": str,
  "answer_summary": str,
  "query_type": str,
  "epoch_context": {
    "epoch_id": str,
    "active_phase": str,
    "gate_ok": bool | None,
    "replay_score": float | None
  },
  "event_window":   int,
  "event_window_hash": sha256 of sorted event ids (hex),
  "answer":         dict,
  "vision_trajectory_score": float | None,
}
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = "71.1"
_DEFAULT_PATH = "data/oracle_answers.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_window_hash(events: Sequence[Mapping[str, Any]]) -> str:
    """Deterministic fingerprint of the event window used by the Oracle.

    ORACLE-DETERM-0: stable for equal ordered event lists.
    """
    ids = [str(e.get("epoch_id", "")) + str(e.get("event_type", "")) for e in events]
    canonical = json.dumps(ids, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class OracleLedger:
    """Append-only JSONL ledger for Oracle query answers.

    Thread-safety: records are written atomically via a single ``write`` +
    ``flush`` call; Python's GIL ensures no interleaving on CPython.

    Usage::

        ledger = OracleLedger()
        ledger.append(query="divergence", answer={...}, events=[...])
    """

    def __init__(self, path: Optional[str | Path] = None) -> None:
        self._path = (
            Path(path)
            if path is not None
            else Path(os.getenv("ADAAD_ORACLE_LEDGER", _DEFAULT_PATH))
        )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(
        self,
        *,
        query: str,
        answer: Dict[str, Any],
        events: Sequence[Mapping[str, Any]],
        vision_trajectory_score: Optional[float] = None,
        query_type: Optional[str] = None,
        answer_summary: Optional[str] = None,
        epoch_context: Optional[Mapping[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Write one oracle answer record to the ledger.

        ORACLE-PERSIST-0: every call writes exactly one JSONL line.
        Returns the written record dict, or None on failure.
        """
        record: Dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "ts": _now_iso(),
            "query": query,
            "normalized_query": " ".join(query.lower().split()),
            "answer_summary": answer_summary or str(answer.get("message", ""))[:240],
            "query_type": query_type or str(answer.get("query_type", "generic")),
            "epoch_context": {
                "epoch_id": str((epoch_context or {}).get("epoch_id", "")),
                "active_phase": str((epoch_context or {}).get("active_phase", "")),
                "gate_ok": (epoch_context or {}).get("gate_ok"),
                "replay_score": (epoch_context or {}).get("replay_score"),
            },
            "event_window": len(events),
            "event_window_hash": _event_window_hash(events),
            "answer": answer,
            "vision_trajectory_score": vision_trajectory_score,
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")
                fh.flush()
            logger.debug(
                "oracle_ledger: appended query=%r window=%d",
                query,
                len(events),
            )
            return record
        except Exception as exc:  # noqa: BLE001
            logger.warning("oracle_ledger: append failed — %s", exc)
            return None

    # ------------------------------------------------------------------
    # Replay / Read
    # ------------------------------------------------------------------

    def replay(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Return the last *limit* oracle records from the ledger (ORACLE-REPLAY-0).

        Returns an empty list if the file does not exist or cannot be read.
        """
        if not self._path.exists():
            return []
        records: List[Dict[str, Any]] = []
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
            for line in lines[-limit:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("oracle_ledger: replay read failed — %s", exc)
        return records

    @property
    def path(self) -> Path:
        return self._path


__all__ = ["OracleLedger"]
