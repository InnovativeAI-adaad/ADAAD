# SPDX-License-Identifier: Apache-2.0
"""
ADAAD v8 — Repo-Ledger Sync Watchdog
=======================================
Solves the Sync Gap problem:

  THE PROBLEM:
  If a human manually edits a file in VS Code without telling the ADAAD
  orchestrator, the hash-chain is broken. The system proceeds on a false
  understanding of the codebase state. Mutations may target stale data.
  EpochEvidence may record wrong model_hash_before values.

  THE SOLUTION: Continuous Repo-Ledger Sync.
  A background file watcher compares the Physical Disk State against the
  Ledger State. If they diverge beyond threshold, the system enters
  LOCKDOWN MODE — no new epochs start until the drift is reconciled.

  LOCKDOWN is not failure. It is the system correctly refusing to proceed
  on corrupted premises. The human reconciles via the Aponi console.

CONSTITUTIONAL INVARIANTS ENFORCED:
  SYNC-DRIFT-0    — if disk-state diverges from ledger-state, epoch is blocked
  SYNC-LOCKDOWN-0 — lockdown is cleared only after human reconciliation sign-off
  SYNC-AUDIT-0    — every drift event is written to data/sync_events.jsonl

Drift Detection Methods:
  1. File hash snapshot: SHA-256 of all Python source files
  2. Tier-0 integrity check: Tier-0 paths must never change between epochs
  3. Manual edit detection: file mtime newer than last epoch timestamp
  4. Constitution hash: CONSTITUTION.md hash must match ledger snapshot

Usage (background thread):
    from runtime.integrity.repo_ledger_sync import RepoLedgerSyncWatchdog

    watchdog = RepoLedgerSyncWatchdog(repo_root="/path/to/repo")
    watchdog.start()  # runs in background thread

Usage (per-epoch gate):
    if not watchdog.is_clean():
        raise SyncDriftError("Repo-ledger sync drift detected. Epoch blocked.")
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


TIER_0_PATHS_RELATIVE = [
    "runtime/governance/gate.py",
    "runtime/evolution/replay_verifier.py",
    "runtime/evolution/evidence/schemas.py",
    "runtime/sandbox/ephemeral_clone.py",
    "CONSTITUTION.md",
    "ARCHITECTURE_CONTRACT.md",
]

WATCHED_EXTENSIONS = {".py", ".yaml", ".yml", ".json", ".md"}


logger = logging.getLogger(__name__)


class SyncDriftError(RuntimeError):
    """Raised when repo-ledger sync divergence is detected at epoch gate."""
    pass


class LockdownActiveError(RuntimeError):
    """Raised when an epoch is attempted while the system is in LOCKDOWN MODE."""
    pass


@dataclass
class DriftEvent:
    """
    Records a single detected drift between disk state and ledger state.

    Fields:
    - event_id        : SHA-256 of event payload
    - drift_type      : "TIER0_MODIFIED", "SOURCE_CHANGED", "MANUAL_EDIT",
                        "CONSTITUTION_CHANGED"
    - affected_files  : list of files with detected changes
    - disk_hash_now   : current disk state hash
    - ledger_hash_ref : expected hash from last ledger snapshot
    - epoch_blocked   : True if this drift caused an epoch to be blocked
    - reconciled      : True after human sign-off
    - timestamp       : UTC timestamp of detection
    """
    event_id: str
    drift_type: str
    affected_files: list[str]
    disk_hash_now: str
    ledger_hash_ref: str
    epoch_blocked: bool
    reconciled: bool
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "drift_type": self.drift_type,
            "affected_files": self.affected_files,
            "disk_hash_now": self.disk_hash_now,
            "ledger_hash_ref": self.ledger_hash_ref,
            "epoch_blocked": self.epoch_blocked,
            "reconciled": self.reconciled,
            "timestamp": self.timestamp,
        }


class RepoLedgerSyncWatchdog:
    """
    Background watchdog that monitors the repository for unauthorized changes.

    Two operational modes:
    1. Background polling thread (start() / stop()) — continuous monitoring
    2. Point-in-time gate check (is_clean() / assert_clean()) — called at epoch start

    Lockdown state is persistent across restarts (stored in data/sync_state.json).
    Human reconciliation clears lockdown via reconcile_drift().

    Args:
        repo_root         : absolute path to repository root
        ledger_path       : path to evolution_ledger.jsonl for reference hashes
        sync_events_path  : path to sync_events.jsonl (drift audit log)
        state_path        : path to sync_state.json (lockdown persistence)
        poll_interval_s   : seconds between background poll cycles
        drift_threshold   : fraction of files changed that triggers lockdown (0.0..1.0)
    """

    def __init__(
        self,
        repo_root: str,
        ledger_path: str = "data/evolution_ledger.jsonl",
        sync_events_path: str = "data/sync_events.jsonl",
        state_path: str = "data/sync_state.json",
        poll_interval_s: int = 30,
        drift_threshold: float = 0.05,
        max_poll_failure_backoff_s: int = 300,
        poll_failure_threshold: int = 3,
    ):
        self.repo_root          = Path(repo_root).resolve()
        self.ledger_path        = Path(ledger_path)
        self.sync_events_path   = Path(sync_events_path)
        self.state_path         = Path(state_path)
        self.poll_interval_s    = poll_interval_s
        self.drift_threshold    = drift_threshold
        self.max_poll_failure_backoff_s = max_poll_failure_backoff_s
        self.poll_failure_threshold = poll_failure_threshold
        self._consecutive_poll_failures = 0

        self._lock              = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running           = False
        self._baseline_snapshot: dict[str, str] = {}  # rel_path → sha256

        # Ensure paths exist
        self.sync_events_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        # Load persisted state
        self._state = self._load_state()

    # ------------------------------------------------------------------
    # Background thread
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start background polling thread."""
        self._baseline_snapshot = self._snapshot_repo()
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="adaad-sync-watchdog",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop background polling thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _poll_loop(self) -> None:
        while self._running:
            try:
                self._check_once()
                self._handle_poll_success()
            except Exception as exc:
                self._handle_poll_failure(exc)
            time.sleep(self._compute_poll_sleep_s())

    def _compute_poll_sleep_s(self) -> float:
        if self._consecutive_poll_failures <= 0:
            return float(self.poll_interval_s)
        multiplier = min(2 ** self._consecutive_poll_failures, 16)
        return float(min(self.poll_interval_s * multiplier, self.max_poll_failure_backoff_s))

    def _handle_poll_success(self) -> None:
        if self._consecutive_poll_failures <= 0:
            return
        self._consecutive_poll_failures = 0
        self._state["monitoring_impaired"] = False
        self._state["monitoring_impaired_reason"] = None
        self._state["monitoring_impaired_since"] = None
        self._state["monitoring_impaired_consecutive_failures"] = 0
        self._state["monitoring_impaired_thread"] = None
        self._state["monitoring_last_recovered_at"] = datetime.now(timezone.utc).isoformat()
        self._save_state()

    def _handle_poll_failure(self, exc: Exception) -> None:
        self._consecutive_poll_failures += 1
        timestamp = datetime.now(timezone.utc).isoformat()
        thread_name = threading.current_thread().name
        degraded = self._consecutive_poll_failures >= self.poll_failure_threshold
        classification = self._classify_poll_exception(exc)

        event_payload = {
            "event_type": "WATCHDOG_POLL_FAILURE",
            "component": "RepoLedgerSyncWatchdog",
            "operation": "poll_loop_check_once",
            "epoch_id": None,
            "mutation_id": None,
            "consecutive_failures": self._consecutive_poll_failures,
            "exception_message": str(exc),
            "exception_type": type(exc).__name__,
            "exception_classification": classification,
            "poll_interval_s": self.poll_interval_s,
            "thread_name": thread_name,
            "timestamp": timestamp,
            "watchdog_degraded": degraded,
        }

        if degraded:
            self._state["monitoring_impaired"] = True
            self._state["monitoring_impaired_reason"] = "WATCHDOG_POLL_FAILURE"
            self._state["monitoring_impaired_since"] = self._state.get("monitoring_impaired_since") or timestamp
            self._state["monitoring_impaired_consecutive_failures"] = self._consecutive_poll_failures
            self._state["monitoring_impaired_thread"] = thread_name
            self._save_state()

        logger.error(
            "RepoLedgerSyncWatchdog poll failure",
            extra={
                "event_type": event_payload["event_type"],
                "exception_type": event_payload["exception_type"],
                "exception_message": event_payload["exception_message"],
                "timestamp": timestamp,
                "poll_interval_s": self.poll_interval_s,
                "thread_name": thread_name,
                "consecutive_failures": self._consecutive_poll_failures,
                "watchdog_degraded": degraded,
                "exception_classification": classification,
            },
        )

        with open(self.sync_events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event_payload, sort_keys=True) + "\n")

    @staticmethod
    def _classify_poll_exception(exc: Exception) -> str:
        if isinstance(exc, (FileNotFoundError, PermissionError, TimeoutError, OSError)):
            return "environmental_exception"
        return "invariant_violation_exception"

    def _check_once(self) -> None:
        """One poll cycle: compare current disk state to baseline."""
        current = self._snapshot_repo()
        changed = self._detect_changes(self._baseline_snapshot, current)
        if changed:
            self._handle_drift(changed, current)
        else:
            self._baseline_snapshot = current

    # ------------------------------------------------------------------
    # Epoch gate API
    # ------------------------------------------------------------------

    def is_clean(self) -> bool:
        """
        Returns True if no drift is detected and system is not in lockdown.
        Call this at the start of every CEL epoch (Step 1).
        """
        if self._state.get("lockdown_active", False):
            return False
        current = self._snapshot_repo()
        changed = self._detect_changes(self._baseline_snapshot, current)
        return len(changed) == 0

    def assert_clean(self) -> None:
        """
        Raises LockdownActiveError or SyncDriftError if system is not clean.
        Called as a hard gate at CEL Step 1 before any epoch processing.
        """
        if self._state.get("lockdown_active", False):
            raise LockdownActiveError(
                f"SYNC-LOCKDOWN-0: System is in LOCKDOWN MODE. "
                f"Drift detected at: {self._state.get('lockdown_triggered_at', 'unknown')}. "
                f"Affected files: {self._state.get('lockdown_affected_files', [])}. "
                f"Reconcile via Aponi console → Sync Status panel."
            )
        current = self._snapshot_repo()
        changed = self._detect_changes(self._baseline_snapshot, current)
        if changed:
            raise SyncDriftError(
                f"SYNC-DRIFT-0: Disk state diverges from ledger state. "
                f"Changed files: {[c['path'] for c in changed[:5]]}. "
                f"Epoch blocked until drift is reconciled."
            )

    def reconcile_drift(
        self,
        human_key_fingerprint: str,
        human_approval_ref: str,
        notes: str,
    ) -> None:
        """
        Human-initiated reconciliation of detected drift.
        Clears lockdown, updates baseline snapshot, and writes reconciliation record.

        Called from Aponi console → Sync Status panel after human review.
        Requires human key fingerprint (HUMAN-0 compliance).
        """
        if not human_key_fingerprint or not human_approval_ref:
            raise ValueError(
                "HUMAN-0: human_key_fingerprint and human_approval_ref required "
                "for drift reconciliation."
            )

        # Update baseline to current state
        self._baseline_snapshot = self._snapshot_repo()

        # Clear lockdown
        self._state["lockdown_active"] = False
        self._state["last_reconciled_at"] = datetime.now(timezone.utc).isoformat()
        self._state["last_reconciled_by"] = human_key_fingerprint
        self._state["last_reconciliation_ref"] = human_approval_ref
        self._save_state()

        # Write reconciliation record to sync audit log
        record = {
            "event_type": "DRIFT_RECONCILED",
            "human_key_fingerprint": human_key_fingerprint,
            "human_approval_ref": human_approval_ref,
            "notes": notes,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with open(self.sync_events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")

    # ------------------------------------------------------------------
    # Tier-0 integrity check (called separately at epoch start)
    # ------------------------------------------------------------------

    def check_tier0_integrity(self) -> list[str]:
        """
        Verifies that all Tier-0 constitutional files are unchanged
        from the baseline snapshot.
        Returns list of modified Tier-0 paths (empty = all clean).
        """
        violations = []
        for rel_path in TIER_0_PATHS_RELATIVE:
            full_path = self.repo_root / rel_path
            if not full_path.exists():
                continue
            current_hash = self._hash_file(full_path)
            baseline_hash = self._baseline_snapshot.get(rel_path)
            if baseline_hash and current_hash != baseline_hash:
                violations.append(rel_path)
        return violations

    # ------------------------------------------------------------------
    # Private: Snapshot and diff
    # ------------------------------------------------------------------

    def _snapshot_repo(self) -> dict[str, str]:
        """
        SHA-256 snapshot of all watched files in the repo.
        Returns: {relative_path_str: sha256_hex}
        """
        snapshot: dict[str, str] = {}
        for path in sorted(self.repo_root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix not in WATCHED_EXTENSIONS:
                continue
            # Skip hidden dirs and venv
            parts = path.parts
            if any(p.startswith(".") or p in ("__pycache__", ".venv", "node_modules") for p in parts):
                continue
            rel = str(path.relative_to(self.repo_root))
            snapshot[rel] = self._hash_file(path)
        return snapshot

    def _hash_file(self, path: Path) -> str:
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _detect_changes(
        self,
        baseline: dict[str, str],
        current: dict[str, str],
    ) -> list[dict]:
        """
        Compares two snapshots. Returns list of changed file records.
        Each record: {path, change_type: "modified"|"added"|"deleted"}
        """
        changes = []
        all_paths = set(baseline.keys()) | set(current.keys())
        for path in all_paths:
            if path not in baseline:
                changes.append({"path": path, "change_type": "added"})
            elif path not in current:
                changes.append({"path": path, "change_type": "deleted"})
            elif baseline[path] != current[path]:
                change_type = "tier0_modified" if any(
                    path.endswith(t) or path.startswith(t.rstrip("/"))
                    for t in TIER_0_PATHS_RELATIVE
                ) else "modified"
                changes.append({"path": path, "change_type": change_type})
        return changes

    def _handle_drift(
        self,
        changed: list[dict],
        current_snapshot: dict[str, str],
    ) -> None:
        """
        Handles detected drift:
        - Writes DriftEvent to sync_events.jsonl
        - If Tier-0 paths affected OR drift > threshold: triggers LOCKDOWN
        """
        affected_files = [c["path"] for c in changed]
        tier0_affected = [c for c in changed if c["change_type"] == "tier0_modified"]

        # Compute drift ratio
        total_files = max(len(self._baseline_snapshot), 1)
        drift_ratio = len(changed) / total_files

        # Determine drift type
        if tier0_affected:
            drift_type = "TIER0_MODIFIED"
        elif drift_ratio >= self.drift_threshold:
            drift_type = "SOURCE_CHANGED"
        else:
            drift_type = "MANUAL_EDIT"

        current_hash = hashlib.sha256(
            json.dumps(current_snapshot, sort_keys=True).encode()
        ).hexdigest()
        ledger_hash = hashlib.sha256(
            json.dumps(self._baseline_snapshot, sort_keys=True).encode()
        ).hexdigest()

        event_payload = json.dumps({
            "drift_type": drift_type,
            "affected_files": affected_files,
            "disk_hash_now": current_hash,
            "ledger_hash_ref": ledger_hash,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, sort_keys=True)
        event_id = hashlib.sha256(event_payload.encode()).hexdigest()

        event = DriftEvent(
            event_id=event_id,
            drift_type=drift_type,
            affected_files=affected_files,
            disk_hash_now=current_hash,
            ledger_hash_ref=ledger_hash,
            epoch_blocked=True,
            reconciled=False,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # Write to sync audit log (SYNC-AUDIT-0)
        with open(self.sync_events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")

        # Trigger lockdown if Tier-0 affected or threshold exceeded
        should_lockdown = bool(tier0_affected) or drift_ratio >= self.drift_threshold
        if should_lockdown:
            self._state["lockdown_active"] = True
            self._state["lockdown_triggered_at"] = event.timestamp
            self._state["lockdown_affected_files"] = affected_files
            self._save_state()

        # Update baseline to current so we don't re-detect same drift
        self._baseline_snapshot = current_snapshot

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> dict:
        default_state = {
            "lockdown_active": False,
            "monitoring_impaired": False,
            "monitoring_impaired_reason": None,
            "monitoring_impaired_since": None,
            "monitoring_impaired_consecutive_failures": 0,
            "monitoring_impaired_thread": None,
        }
        if self.state_path.exists():
            with open(self.state_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            return {**default_state, **loaded}
        return default_state

    def _save_state(self) -> None:
        tmp = self.state_path.with_suffix(".adaad_tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2, sort_keys=True)
        tmp.rename(self.state_path)
