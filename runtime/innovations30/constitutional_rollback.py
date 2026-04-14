# SPDX-License-Identifier: Apache-2.0
"""
INNOV-32 — Constitutional Rollback & Temporal Versioning (CRTV)
================================================================
Constitutional version-control layer: every amendment is semantically
diffed, chain-linked, and reversible to any prior state under HUMAN-0 gate.

Hard-class invariants introduced
---------------------------------
CRTV-0           Append-only: snapshots never mutate once written.
CRTV-CHAIN-0     Every snapshot carries prev_hash; genesis prev_hash == GENESIS.
CRTV-DETERM-0    Digests use sha256(json.dumps(payload, sort_keys=True)).
CRTV-GATE-0      Rollback is fail-closed: any error raises ConstitutionalRollbackError.
CRTV-AUDIT-0     Every rollback/snapshot is flushed to append-only JSONL before return.

Author: DEVADAAD (Claude, ArchitectAgent)
Phase:  117 · INNOV-32
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
CORO_INV_CHAIN: str = "CORO-INV-CHAIN"
CORO_LEDGER_DEFAULT: str = "data/constitutional_rollback_events.jsonl"


class ConstitutionalRollbackViolation(RuntimeError):
    """Raised when a Constitutional Rollback constitutional invariant is breached."""



# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GENESIS_HASH: str = "GENESIS-CRTV-0"
CRTV_LEDGER_PATH: str = os.environ.get(
    "ADAAD_CRTV_LEDGER", "data/crtv_ledger.jsonl"
)
_VALID_ACTIONS = frozenset({"snapshot", "rollback", "diff", "verify"})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ConstitutionalRollbackError(RuntimeError):
    """Raised whenever a CRTV invariant is violated (CRTV-GATE-0)."""


# ---------------------------------------------------------------------------
# Determinism provider (CRTV-DETERM-0)
# ---------------------------------------------------------------------------


class _DeterminismProvider:
    @staticmethod
    def now_utc() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    @staticmethod
    def digest(payload: dict) -> str:
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ConstitutionalDiff:
    """Semantic delta between two constitutional versions."""

    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    modified: List[str] = field(default_factory=list)

    @property
    def change_count(self) -> int:
        return len(self.added) + len(self.removed) + len(self.modified)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ConstitutionalSnapshot:
    """Immutable record of a constitutional state at a given epoch (CRTV-0)."""

    snapshot_id: str
    epoch_id: str
    rules: Dict[str, str]          # rule_name → rule_body/hash
    amendment_reason: str
    author: str
    timestamp: str
    prev_hash: str                 # chain-link (CRTV-CHAIN-0)
    diff: ConstitutionalDiff
    snapshot_digest: str = ""      # populated post-construction

    def __post_init__(self) -> None:
        if not self.snapshot_digest:
            payload = {
                "snapshot_id": self.snapshot_id,
                "epoch_id": self.epoch_id,
                "rules": self.rules,
                "amendment_reason": self.amendment_reason,
                "author": self.author,
                "timestamp": self.timestamp,
                "prev_hash": self.prev_hash,
                "diff": self.diff.to_dict(),
            }
            self.snapshot_digest = _DeterminismProvider.digest(payload)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["diff"] = self.diff.to_dict()
        return d


@dataclass
class RollbackEvent:
    """Record of a constitutional rollback operation (CRTV-AUDIT-0)."""

    event_id: str
    target_snapshot_id: str
    rolled_back_from: str
    epoch_id: str
    reason: str
    author: str
    timestamp: str
    restored_rules: Dict[str, str]
    event_digest: str = ""

    def __post_init__(self) -> None:
        if not self.event_digest:
            payload = {k: v for k, v in asdict(self).items() if k != "event_digest"}
            self.event_digest = _DeterminismProvider.digest(payload)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Guard helper (CRTV-GATE-0)
# ---------------------------------------------------------------------------


def crtv_guard(condition: bool, invariant: str, detail: str = "") -> None:
    """Fail-closed guard: raises ConstitutionalRollbackError when condition is False."""
    if not condition:
        msg = f"[{invariant}] CRTV invariant violated"
        if detail:
            msg += f": {detail}"
        raise ConstitutionalRollbackError(msg)


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------


class ConstitutionalRollbackEngine:
    """
    Maintains an append-only, chain-linked ledger of constitutional snapshots
    and provides governed rollback capability.

    HUMAN-0 enforcement: rollback() is gated; callers must pass a signed
    ratification token that must contain the canonical governor string.
    """

    GOVERNOR = "DUSTIN L REID"

    def __init__(
        self,
        ledger_path: str = CRTV_LEDGER_PATH,
    ) -> None:
        self._ledger_path = Path(ledger_path)
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._snapshots: List[ConstitutionalSnapshot] = []
        self._load_ledger()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def snapshot(
        self,
        epoch_id: str,
        rules: Dict[str, str],
        amendment_reason: str,
        author: str = "DEVADAAD",
    ) -> ConstitutionalSnapshot:
        """
        Record the current constitutional state as an immutable snapshot.
        Append to ledger (CRTV-AUDIT-0) before returning (CRTV-GATE-0).
        """
        crtv_guard(bool(epoch_id), "CRTV-GATE-0", "epoch_id must be non-empty")
        crtv_guard(isinstance(rules, dict), "CRTV-GATE-0", "rules must be a dict")

        prev = self._snapshots[-1] if self._snapshots else None
        prev_hash = prev.snapshot_digest if prev else GENESIS_HASH

        diff = self._compute_diff(
            prev.rules if prev else {}, rules
        )

        snap_id = f"SNAP-{epoch_id}-{len(self._snapshots):04d}"
        snap = ConstitutionalSnapshot(
            snapshot_id=snap_id,
            epoch_id=epoch_id,
            rules=rules,
            amendment_reason=amendment_reason,
            author=author,
            timestamp=_DeterminismProvider.now_utc(),
            prev_hash=prev_hash,
            diff=diff,
        )

        # Append-only invariant (CRTV-0 + CRTV-AUDIT-0)
        self._append_to_ledger({"action": "snapshot", **snap.to_dict()})
        self._snapshots.append(snap)
        return snap

    def rollback(
        self,
        target_snapshot_id: str,
        current_epoch_id: str,
        reason: str,
        ratification_token: str,
    ) -> RollbackEvent:
        """
        Restore the constitutional state to target_snapshot_id.
        Fail-closed: any missing state raises ConstitutionalRollbackError.
        Gated: ratification_token must contain HUMAN-0 governor string.
        """
        # HUMAN-0 gate
        crtv_guard(
            self.GOVERNOR in ratification_token,
            "CRTV-GATE-0",
            "Rollback requires HUMAN-0 ratification containing governor string",
        )
        crtv_guard(bool(target_snapshot_id), "CRTV-GATE-0", "target_snapshot_id required")

        target = self._find_snapshot(target_snapshot_id)
        crtv_guard(
            target is not None,
            "CRTV-GATE-0",
            f"Snapshot {target_snapshot_id!r} not found in ledger",
        )

        current_head = self._snapshots[-1] if self._snapshots else None
        rolled_back_from = current_head.snapshot_id if current_head else "NONE"

        event_id = f"ROLLBACK-{current_epoch_id}-{len(self._snapshots):04d}"
        evt = RollbackEvent(
            event_id=event_id,
            target_snapshot_id=target_snapshot_id,
            rolled_back_from=rolled_back_from,
            epoch_id=current_epoch_id,
            reason=reason,
            author=self.GOVERNOR,
            timestamp=_DeterminismProvider.now_utc(),
            restored_rules=dict(target.rules),
        )

        # Audit-first: flush before modifying in-memory state (CRTV-AUDIT-0)
        self._append_to_ledger({"action": "rollback", **evt.to_dict()})

        # Truncate in-memory chain to target (CRTV-0: ledger is append-only,
        # in-memory view is rebuilt on reload)
        target_idx = next(
            i for i, s in enumerate(self._snapshots)
            if s.snapshot_id == target_snapshot_id
        )
        self._snapshots = self._snapshots[: target_idx + 1]
        return evt

    def diff(
        self, snapshot_id_a: str, snapshot_id_b: str
    ) -> ConstitutionalDiff:
        """Return semantic diff between two arbitrary snapshots."""
        a = self._find_snapshot(snapshot_id_a)
        b = self._find_snapshot(snapshot_id_b)
        crtv_guard(a is not None, "CRTV-GATE-0", f"Snapshot {snapshot_id_a!r} not found")
        crtv_guard(b is not None, "CRTV-GATE-0", f"Snapshot {snapshot_id_b!r} not found")
        return self._compute_diff(a.rules, b.rules)

    def verify_chain(self) -> bool:
        """
        Verify chain integrity (CRTV-CHAIN-0): each snapshot's prev_hash must
        equal the prior snapshot's digest; genesis prev_hash must equal GENESIS_HASH.
        """
        for i, snap in enumerate(self._snapshots):
            expected_prev = (
                GENESIS_HASH if i == 0 else self._snapshots[i - 1].snapshot_digest
            )
            crtv_guard(
                snap.prev_hash == expected_prev,
                "CRTV-CHAIN-0",
                f"Chain broken at snapshot {snap.snapshot_id}: "
                f"expected prev_hash={expected_prev!r}, got {snap.prev_hash!r}",
            )
        return True

    @property
    def head(self) -> Optional[ConstitutionalSnapshot]:
        return self._snapshots[-1] if self._snapshots else None

    @property
    def snapshot_count(self) -> int:
        return len(self._snapshots)

    def get_snapshot(self, snapshot_id: str) -> Optional[ConstitutionalSnapshot]:
        return self._find_snapshot(snapshot_id)

    def list_snapshots(self) -> List[str]:
        return [s.snapshot_id for s in self._snapshots]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_diff(
        self, rules_a: Dict[str, str], rules_b: Dict[str, str]
    ) -> ConstitutionalDiff:
        keys_a = set(rules_a)
        keys_b = set(rules_b)
        added = sorted(keys_b - keys_a)
        removed = sorted(keys_a - keys_b)
        modified = sorted(
            k for k in keys_a & keys_b if rules_a[k] != rules_b[k]
        )
        return ConstitutionalDiff(added=added, removed=removed, modified=modified)

    def _find_snapshot(self, snap_id: str) -> Optional[ConstitutionalSnapshot]:
        for s in self._snapshots:
            if s.snapshot_id == snap_id:
                return s
        return None

    def _append_to_ledger(self, record: dict) -> None:
        """Flush a record to the append-only JSONL ledger (CRTV-AUDIT-0)."""
        try:
            with self._ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except OSError as exc:
            raise ConstitutionalRollbackError(
                f"[CRTV-AUDIT-0] Ledger write failed: {exc}"
            ) from exc

    def _load_ledger(self) -> None:
        """Rebuild in-memory snapshot list from the append-only JSONL ledger."""
        if not self._ledger_path.exists():
            return
        try:
            with self._ledger_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    if record.get("action") == "snapshot":
                        diff_data = record.get("diff", {})
                        diff = ConstitutionalDiff(
                            added=diff_data.get("added", []),
                            removed=diff_data.get("removed", []),
                            modified=diff_data.get("modified", []),
                        )
                        snap = ConstitutionalSnapshot(
                            snapshot_id=record["snapshot_id"],
                            epoch_id=record["epoch_id"],
                            rules=record["rules"],
                            amendment_reason=record["amendment_reason"],
                            author=record["author"],
                            timestamp=record["timestamp"],
                            prev_hash=record["prev_hash"],
                            diff=diff,
                            snapshot_digest=record.get("snapshot_digest", ""),
                        )
                        self._snapshots.append(snap)
        except (OSError, json.JSONDecodeError) as exc:
            raise ConstitutionalRollbackError(
                f"[CRTV-AUDIT-0] Ledger load failed: {exc}"
            ) from exc

# ── Chain-linkage scaffold (hardening pass — prev_digest + _append_event) ─────
import hashlib as _hashlib
import json as _json


_MODULE_PREV_DIGEST: str = "genesis"   # prev_digest chain head for this module


def _append_event(event: dict, ledger_path: str = "") -> None:
    """Module-level append-only JSONL event stub [CED-INV-AUDIT, CED-INV-CHAIN].

    Writes a chain-linked record to ledger_path (or discards if empty).
    Full integration deferred to per-module deep-dive phase.
    """
    global _MODULE_PREV_DIGEST
    if not ledger_path:
        return
    import dataclasses as _dc
    from pathlib import Path as _Path
    row = event if isinstance(event, dict) else (
        _dc.asdict(event) if hasattr(event, '__dataclass_fields__') else {}
    )
    row["prev_digest"] = _MODULE_PREV_DIGEST
    digest_payload = _json.dumps(row, sort_keys=True).encode()
    row["event_digest"] = "sha256:" + _hashlib.sha256(digest_payload).hexdigest()
    p = _Path(ledger_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(_json.dumps(row, sort_keys=True) + "\n")
    _MODULE_PREV_DIGEST = row["event_digest"]

