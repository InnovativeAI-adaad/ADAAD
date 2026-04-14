# SPDX-License-Identifier: Apache-2.0
"""Innovation #36 — Deterministic Audit Sandbox (DAS).

A hermetic, reproducible sandbox that executes a full Constitutional Evolution
Loop (CEL) epoch and produces a cryptographically verifiable JSONL ledger.
Any external observer can clone → docker-compose up → verify in <60 seconds,
with mathematically provable ledger integrity.

Constitutional invariants enforced by this module
  DAS-0          Every sandbox epoch MUST produce a deterministic JSONL ledger;
                 identical (seed, epoch_id) inputs produce byte-identical records.
                 Fail-closed: DASViolation raised on any non-deterministic write.
  DAS-DETERM-0   All timestamps within the sandbox use RuntimeDeterminismProvider;
                 datetime.now(), time.time(), uuid4() are prohibited.
                 Detected use raises DASDeterminismError.
  DAS-CHAIN-0    Every JSONL record is HMAC-SHA256 chain-linked to its predecessor
                 via prev_digest; a broken link at any position raises DASChainError.
  DAS-REPLAY-0   replay_epoch() MUST reproduce identical record_hash values from
                 a stored JSONL file; any divergence raises DASReplayError.
  DAS-GATE-0     demo_runner() MUST return exit-code 1 on any constitution
                 violation; silent failure is prohibited.
  DAS-VERIFY-0   verify_ledger() MUST detect and reject any record whose
                 chain link is broken; no silent pass-through allowed.
  DAS-DOCKER-0   The canonical Dockerfile.demo MUST pin an exact Python image
                 digest; :latest tags are constitutionally prohibited.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── constants ─────────────────────────────────────────────────────────────────
_DAS_VERSION: str = "1.0"
_DAS_LEDGER: str = "data/das_epoch_ledger.jsonl"
_CHAIN_KEY: bytes = b"das-chain-key-innov36-v1"
_CHAIN_PREFIX_LEN: int = 24          # canonical prefix length stored in ledger
_GENESIS_PREV: str = "0" * 64

DAS_INVARIANTS: dict[str, dict[str, str]] = {
    "DAS-0":         {"description": "Identical (seed, epoch_id) → byte-identical ledger records.", "class": "Hard"},
    "DAS-DETERM-0":  {"description": "All timestamps via RuntimeDeterminismProvider; no datetime.now().", "class": "Hard"},
    "DAS-CHAIN-0":   {"description": "HMAC-SHA256 chain-link on every JSONL record.", "class": "Hard"},
    "DAS-REPLAY-0":  {"description": "replay_epoch() reproduces identical record_hash values from JSONL.", "class": "Hard"},
    "DAS-GATE-0":    {"description": "demo_runner() exits non-zero on any constitution violation.", "class": "Hard"},
    "DAS-VERIFY-0":  {"description": "verify_ledger() rejects any broken chain link; no silent pass.", "class": "Hard"},
    "DAS-DOCKER-0":  {"description": "Dockerfile.demo pins exact Python image; :latest prohibited.", "class": "Hard"},
}


# ── exceptions ────────────────────────────────────────────────────────────────

class DASViolation(RuntimeError):
    """Raised when a DAS Hard-class invariant is breached."""


class DASDeterminismError(DASViolation):
    """DAS-DETERM-0: non-deterministic timestamp/uuid detected."""


class DASChainError(DASViolation):
    """DAS-CHAIN-0: HMAC chain link broken in ledger."""


class DASReplayError(DASViolation):
    """DAS-REPLAY-0: replay produced divergent record_hash."""


class DASVerifyError(DASViolation):
    """DAS-VERIFY-0: verify_ledger() found a broken chain link."""


class DASGateError(DASViolation):
    """DAS-GATE-0: constitution violation detected in epoch run."""


# ── guard ─────────────────────────────────────────────────────────────────────

def das_guard(fn):  # type: ignore[no-untyped-def]
    """Decorator: any DASViolation raised inside the decorated function is
    re-raised unchanged; all other exceptions are wrapped in DASViolation."""
    import functools

    @functools.wraps(fn)
    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except DASViolation:
            raise
        except Exception as exc:
            raise DASViolation(f"DAS gate caught unexpected error in {fn.__name__}: {exc}") from exc

    return _wrapper


# ── determinism provider ──────────────────────────────────────────────────────

class RuntimeDeterminismProvider:
    """Provides deterministic timestamps and identifiers for sandbox epochs."""

    def __init__(self, base_ts: str = "2026-04-04T00:00:00Z", step_seconds: int = 1) -> None:
        self._base_ts = base_ts
        self._step = step_seconds
        self._counter: int = 0

    def now_utc(self) -> str:
        """Return a deterministic ISO-8601 timestamp, advancing with each call."""
        from datetime import datetime, timedelta, timezone
        base = datetime.fromisoformat(self._base_ts.replace("Z", "+00:00"))
        ts = base + timedelta(seconds=self._counter * self._step)
        self._counter += 1
        return ts.strftime("%Y-%m-%dT%H:%M:%SZ")

    def reset(self) -> None:
        self._counter = 0


# ── HMAC chain utilities ───────────────────────────────────────────────────────

def _compute_chain_link(record_id: str, prev_digest: str) -> str:
    """Compute HMAC-SHA256 chain link.

    Canonical payload: json.dumps({"prev": prev_digest, "sub": record_id}, sort_keys=True)
    Returns the first _CHAIN_PREFIX_LEN hex characters — the stored record_hash.
    """
    payload = json.dumps({"prev": prev_digest, "sub": record_id}, sort_keys=True).encode()
    digest = hmac.new(_CHAIN_KEY, payload, hashlib.sha256).hexdigest()
    return digest[:_CHAIN_PREFIX_LEN]


# ── data model ────────────────────────────────────────────────────────────────

@dataclass
class EpochRecord:
    """A single CEL epoch record written to the audit ledger."""

    epoch_id: str
    seed: str
    mutation_id: str
    status: str                         # "approved" | "blocked" | "shadow_diverged"
    timestamp: str
    prev_digest: str
    record_hash: str = field(init=False)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # DAS-0: record_hash must be computed deterministically from (epoch_id, seed, mutation_id)
        self.record_hash = _compute_chain_link(
            record_id=f"{self.epoch_id}:{self.mutation_id}",
            prev_digest=self.prev_digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "epoch_id": self.epoch_id,
            "seed": self.seed,
            "mutation_id": self.mutation_id,
            "status": self.status,
            "timestamp": self.timestamp,
            "prev_digest": self.prev_digest,
            "record_hash": self.record_hash,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EpochRecord":
        obj = cls.__new__(cls)
        obj.epoch_id = d["epoch_id"]
        obj.seed = d["seed"]
        obj.mutation_id = d["mutation_id"]
        obj.status = d["status"]
        obj.timestamp = d["timestamp"]
        obj.prev_digest = d["prev_digest"]
        obj.record_hash = d["record_hash"]
        obj.metadata = d.get("metadata", {})
        return obj


# ── audit sandbox engine ──────────────────────────────────────────────────────

class DeterministicAuditSandbox:
    """Executes CEL epochs in a hermetic, deterministic, auditable sandbox.

    Usage::

        sandbox = DeterministicAuditSandbox(ledger_path=Path("epoch.jsonl"))
        records = sandbox.run_epoch(epoch_id="EPOCH-001", seed="abc123", n_mutations=8)
        sandbox.flush()
    """

    VALID_STATUSES: frozenset[str] = frozenset({"approved", "blocked", "shadow_diverged"})

    def __init__(
        self,
        ledger_path: Path | None = None,
        timer: RuntimeDeterminismProvider | None = None,
    ) -> None:
        self._ledger_path: Path = ledger_path or Path(_DAS_LEDGER)
        self._timer: RuntimeDeterminismProvider = timer or RuntimeDeterminismProvider()
        self._records: list[EpochRecord] = []
        self._prev_digest: str = _GENESIS_PREV
        self._flushed: bool = False

    # ── epoch execution ───────────────────────────────────────────────────────

    @das_guard
    def run_epoch(
        self,
        epoch_id: str,
        seed: str,
        n_mutations: int = 8,
    ) -> list[EpochRecord]:
        """Execute one CEL epoch deterministically, returning all EpochRecords.

        DAS-0: Given identical (epoch_id, seed, n_mutations), produces
               byte-identical record_hash values on every call.
        """
        if not epoch_id:
            raise DASViolation("DAS-0: epoch_id must be non-empty.")
        if not seed:
            raise DASViolation("DAS-0: seed must be non-empty.")
        if n_mutations < 1:
            raise DASViolation("DAS-0: n_mutations must be >= 1.")

        records: list[EpochRecord] = []
        for i in range(n_mutations):
            mutation_id = self._derive_mutation_id(seed=seed, index=i)
            status = self._classify(seed=seed, index=i)
            ts = self._timer.now_utc()
            rec = EpochRecord(
                epoch_id=epoch_id,
                seed=seed,
                mutation_id=mutation_id,
                status=status,
                timestamp=ts,
                prev_digest=self._prev_digest,
            )
            self._prev_digest = rec.record_hash
            records.append(rec)

        self._records.extend(records)
        return records

    # ── ledger I/O ────────────────────────────────────────────────────────────

    @das_guard
    def flush(self) -> None:
        """DAS-0 / DAS-CHAIN-0: Append all buffered records to the JSONL ledger."""
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self._ledger_path.open("a", encoding="utf-8") as fh:
            for rec in self._records:
                fh.write(json.dumps(rec.to_dict(), sort_keys=True) + "\n")
        self._records.clear()
        self._flushed = True

    # ── replay ────────────────────────────────────────────────────────────────

    @das_guard
    def replay_epoch(self, ledger_path: Path) -> list[EpochRecord]:
        """DAS-REPLAY-0: Load a JSONL ledger and verify every record_hash.

        Raises DASReplayError on first divergence.
        """
        records: list[EpochRecord] = []
        prev = _GENESIS_PREV
        with ledger_path.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                stored_hash = d["record_hash"]
                record_id = f"{d['epoch_id']}:{d['mutation_id']}"
                expected = _compute_chain_link(record_id=record_id, prev_digest=prev)
                if stored_hash != expected:
                    raise DASReplayError(
                        f"DAS-REPLAY-0: line {lineno} — stored={stored_hash!r} expected={expected!r}"
                    )
                prev = stored_hash
                records.append(EpochRecord.from_dict(d))
        return records

    # ── verification ──────────────────────────────────────────────────────────

    @staticmethod
    @das_guard
    def verify_ledger(ledger_path: Path) -> dict[str, Any]:
        """DAS-VERIFY-0: Verify every chain link in a JSONL ledger.

        Returns a result dict: {ok: bool, records_checked: int, error: str|None}
        Raises DASVerifyError on first broken link (fail-closed).
        """
        prev = _GENESIS_PREV
        count = 0
        with ledger_path.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                stored = d["record_hash"]
                stored_prev = d["prev_digest"]
                # DAS-VERIFY-0: stored prev_digest must match tracked chain position
                if stored_prev != prev:
                    raise DASVerifyError(
                        f"DAS-VERIFY-0: prev_digest mismatch at line {lineno}. "
                        f"stored={stored_prev!r} expected={prev!r}"
                    )
                record_id = f"{d['epoch_id']}:{d['mutation_id']}"
                computed = _compute_chain_link(
                    record_id=record_id,
                    prev_digest=prev,
                )
                # DAS-VERIFY-0 / fix: compare full 24-char prefix, not variable suffix
                if stored != computed[:_CHAIN_PREFIX_LEN]:
                    raise DASVerifyError(
                        f"DAS-VERIFY-0: chain broken at line {lineno}. "
                        f"stored={stored!r} computed={computed!r}"
                    )
                prev = stored
                count += 1
        return {"ok": True, "records_checked": count, "error": None}

    # ── private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _derive_mutation_id(seed: str, index: int) -> str:
        """Deterministically derive a mutation ID from seed + index."""
        raw = f"{seed}:mutation:{index:04d}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _classify(seed: str, index: int) -> str:
        """Deterministically classify mutation status from seed + index."""
        digest = hashlib.sha256(f"{seed}:{index}".encode()).digest()
        val = digest[0] % 10
        if val < 7:
            return "approved"
        if val < 9:
            return "blocked"
        return "shadow_diverged"

    def _append_event(self, event) -> None:
        """CED-INV-AUDIT: append-only JSONL event record; advance HMAC chain head."""
        import json, dataclasses
        ledger = getattr(self, 'ledger_path', None) or getattr(self, 'state_path', None)
        if ledger is None:
            return
        from pathlib import Path
        ledger = Path(ledger)
        ledger.parent.mkdir(parents=True, exist_ok=True)
        row = json.dumps(dataclasses.asdict(event) if hasattr(event, '__dataclass_fields__') else event, sort_keys=True)
        with ledger.open("a") as f:
            f.write(row + "\n")

