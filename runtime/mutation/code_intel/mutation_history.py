# SPDX-License-Identifier: Apache-2.0
"""
runtime.mutation.code_intel.mutation_history
============================================
Append-only, hash-chained JSONL ledger of code mutation events.

Invariants
----------
INTEL-TS-0   All timestamps via RuntimeDeterminismProvider.now_utc().
INTEL-DET-0  Each record carries a sha256 chain-hash over its content + prior hash.
INTEL-ISO-0  Zero imports from runtime.governance or runtime.ledger paths.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Determinism provider — lightweight shim (no governance import)
# ---------------------------------------------------------------------------

class _LocalDeterminismProvider:
    """Minimal determinism shim used when the full provider is unavailable."""

    @staticmethod
    def now_utc() -> str:
        import datetime
        return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00","Z")


def _get_provider() -> Any:
    try:
        # Attempt canonical provider without touching governance paths
        from runtime.determinism import RuntimeDeterminismProvider  # type: ignore
        return RuntimeDeterminismProvider
    except ImportError:
        return _LocalDeterminismProvider


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class IntegrityError(Exception):
    """Raised when a ledger entry fails chain-hash verification."""


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------

@dataclass
class MutationRecord:
    """A single mutation event recorded in the ledger.

    Fields
    ------
    sequence_id   Monotonically increasing record index (0-based).
    timestamp     ISO-8601 UTC string (INTEL-TS-0).
    target_file   Source file that was mutated.
    mutation_type Short label, e.g. 'refactor', 'hotfix', 'generated'.
    description   Free-text description of the change.
    metadata      Arbitrary key-value pairs for enrichment data.
    prior_hash    chain_hash of the previous record ('0'*64 for first entry).
    chain_hash    sha256 of this record's content + prior_hash (INTEL-DET-0).
    """

    sequence_id: int
    timestamp: str
    target_file: str
    mutation_type: str
    description: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    prior_hash: str = "0" * 64
    chain_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "sequence_id": self.sequence_id,
            "timestamp": self.timestamp,
            "target_file": self.target_file,
            "mutation_type": self.mutation_type,
            "description": self.description,
            "metadata": self.metadata,
            "prior_hash": self.prior_hash,
            "chain_hash": self.chain_hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MutationRecord":
        r = cls(
            sequence_id=data["sequence_id"],
            timestamp=data["timestamp"],
            target_file=data["target_file"],
            mutation_type=data["mutation_type"],
            description=data["description"],
            metadata=data.get("metadata", {}),
            prior_hash=data.get("prior_hash", "0" * 64),
            chain_hash=data.get("chain_hash", ""),
        )
        return r

    def compute_hash(self) -> str:
        payload = json.dumps(
            {
                "sequence_id": self.sequence_id,
                "timestamp": self.timestamp,
                "target_file": self.target_file,
                "mutation_type": self.mutation_type,
                "description": self.description,
                "metadata": self.metadata,
                "prior_hash": self.prior_hash,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

class MutationHistory:
    """Append-only hash-chained mutation ledger.

    Storage
    -------
    Each record is written as a single-line JSON string to a JSONL file.
    In-memory mode is used when no *ledger_path* is provided.

    Usage
    -----
    history = MutationHistory()
    history.append("src/foo.py", "refactor", "Extracted helper function")
    assert history.verify_integrity()
    """

    def __init__(self, ledger_path: Optional[str] = None) -> None:
        self._path: Optional[Path] = Path(ledger_path) if ledger_path else None
        self._records: List[MutationRecord] = []
        self._provider = _get_provider()

        if self._path and self._path.exists():
            self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(
        self,
        target_file: str,
        mutation_type: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MutationRecord:
        """Append a new mutation record to the ledger."""
        prior_hash = self._records[-1].chain_hash if self._records else "0" * 64
        seq = len(self._records)
        ts = self._provider.now_utc()

        record = MutationRecord(
            sequence_id=seq,
            timestamp=ts,
            target_file=target_file,
            mutation_type=mutation_type,
            description=description,
            metadata=metadata or {},
            prior_hash=prior_hash,
        )
        record.chain_hash = record.compute_hash()
        self._records.append(record)

        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record.to_dict()) + "\n")

        return record

    def verify_integrity(self) -> bool:
        """Verify the full chain from record 0 to the latest entry.

        Returns True if intact, raises IntegrityError on first violation.
        """
        expected_prior = "0" * 64
        for rec in self._records:
            if rec.prior_hash != expected_prior:
                raise IntegrityError(
                    f"Chain broken at sequence_id={rec.sequence_id}: "
                    f"expected prior_hash={expected_prior}, got {rec.prior_hash}"
                )
            computed = rec.compute_hash()
            if rec.chain_hash != computed:
                raise IntegrityError(
                    f"Hash mismatch at sequence_id={rec.sequence_id}: "
                    f"stored={rec.chain_hash}, computed={computed}"
                )
            expected_prior = rec.chain_hash
        return True

    @property
    def records(self) -> List[MutationRecord]:
        return list(self._records)

    @property
    def count(self) -> int:
        return len(self._records)

    def latest(self) -> Optional[MutationRecord]:
        return self._records[-1] if self._records else None

    def records_for_file(self, filepath: str) -> List[MutationRecord]:
        return [r for r in self._records if r.target_file == filepath]

    def churn_map(self) -> Dict[str, int]:
        """Return a dict mapping filepath → mutation count."""
        counts: Dict[str, int] = {}
        for r in self._records:
            counts[r.target_file] = counts.get(r.target_file, 0) + 1
        return counts

    def normalised_churn_map(self) -> Dict[str, float]:
        """Return churn counts normalised to [0, 1] by max count."""
        raw = self.churn_map()
        if not raw:
            return {}
        max_count = max(raw.values())
        if max_count == 0:
            return {k: 0.0 for k in raw}
        return {k: v / max_count for k, v in raw.items()}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> None:
        assert self._path is not None
        with open(self._path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    self._records.append(MutationRecord.from_dict(data))
                except (json.JSONDecodeError, KeyError):
                    continue
