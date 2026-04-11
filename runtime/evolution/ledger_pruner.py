# SPDX-License-Identifier: Apache-2.0
"""
ADAAD v8 — Ledger Pruner (Epoch Summarization Engine)
=======================================================
Solves the Ledger Performance & State Bloat problem.

  THE PROBLEM:
  In high-frequency autonomous development, evolution_ledger.jsonl grows
  exponentially. Every "thought" and failed mutation is hash-chained.
  Eventually the system crawls to a halt reading/writing a multi-GB file.

  THE SOLUTION: Epoch Summarization (Blockchain-style State Pruning).
  - "Full Nodes"  = complete history in data/evolution_ledger.jsonl
  - "Light State" = current state + last N hashes in data/ledger_state.json
  - Every SNAPSHOT_INTERVAL epochs: generate a Root State Hash (checkpoint)
  - Archive entries older than the last checkpoint into data/archives/
  - The cryptographic chain is NEVER broken — archive root hash bridges the gap

CONSTITUTIONAL INVARIANTS ENFORCED:
  LEDGER-ARCH-0   — archived entries remain hash-verifiable via root state hash
  LEDGER-PRUNE-0  — active ledger always maintains at least RETENTION_EPOCHS epochs
  LEDGER-CHAIN-0  — chain integrity is verified before and after every pruning operation

Usage:
    from runtime.evolution.ledger_pruner import LedgerPruner

    pruner = LedgerPruner(ledger_path="data/evolution_ledger.jsonl")
    if pruner.should_prune():
        summary = pruner.prune_and_archive()
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Configuration defaults (overridden by config/governance/static_rules.yaml)
# ---------------------------------------------------------------------------
DEFAULT_SNAPSHOT_INTERVAL = 1000   # epochs between checkpoints
DEFAULT_RETENTION_EPOCHS  = 100    # minimum epochs kept in active ledger
DEFAULT_MAX_LEDGER_SIZE_MB = 512   # trigger pruning if ledger exceeds this


@dataclass(frozen=True)
class LedgerSummary:
    """
    Result of a pruning + archive operation.

    Fields:
    - checkpoint_hash     : SHA-256 of all archived entries (Root State Hash)
    - entries_archived    : number of JSONL lines moved to archive
    - entries_retained    : number of JSONL lines remaining in active ledger
    - archive_file        : path to the compressed archive file
    - chain_verified      : True if hash chain was verified before archiving
    - ledger_size_before_mb : ledger size before pruning
    - ledger_size_after_mb  : ledger size after pruning
    - timestamp           : UTC timestamp of pruning operation
    """
    checkpoint_hash: str
    entries_archived: int
    entries_retained: int
    archive_file: str
    chain_verified: bool
    ledger_size_before_mb: float
    ledger_size_after_mb: float
    timestamp: str


class LedgerIntegrityError(RuntimeError):
    """Raised when hash chain verification fails before or after pruning."""
    pass


class LedgerPruner:
    """
    Manages the append-only evolution ledger lifecycle:
    - Monitors file size and epoch count
    - Triggers summarization at configurable intervals
    - Archives old entries while preserving cryptographic chain continuity
    - Updates the light-state file for fast access

    The pruner never deletes records — it compresses and archives them.
    The checkpoint_hash in ledger_state.json bridges the gap between
    the archived history and the active ledger, ensuring full replay
    is possible from archive + active ledger.

    Args:
        ledger_path         : path to data/evolution_ledger.jsonl
        archive_dir         : path to data/archives/ (default: alongside ledger)
        state_path          : path to data/ledger_state.json
        snapshot_interval   : epochs between checkpoints
        retention_epochs    : minimum epochs to keep in active ledger
        max_ledger_size_mb  : trigger pruning if ledger exceeds this
    """

    def __init__(
        self,
        ledger_path: str = "data/evolution_ledger.jsonl",
        archive_dir: Optional[str] = None,
        state_path: Optional[str] = None,
        snapshot_interval: int = DEFAULT_SNAPSHOT_INTERVAL,
        retention_epochs: int = DEFAULT_RETENTION_EPOCHS,
        max_ledger_size_mb: float = DEFAULT_MAX_LEDGER_SIZE_MB,
    ):
        self.ledger_path = Path(ledger_path)
        self.archive_dir = Path(archive_dir) if archive_dir else self.ledger_path.parent / "archives"
        self.state_path  = Path(state_path) if state_path else self.ledger_path.parent / "ledger_state.json"
        self.snapshot_interval  = snapshot_interval
        self.retention_epochs   = retention_epochs
        self.max_ledger_size_mb = max_ledger_size_mb

        self.archive_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def should_prune(self) -> bool:
        """
        Returns True if pruning should be triggered.
        Conditions: epoch count >= snapshot_interval OR file size >= max_ledger_size_mb.
        """
        if not self.ledger_path.exists():
            return False

        size_mb = self.ledger_path.stat().st_size / (1024 * 1024)
        if size_mb >= self.max_ledger_size_mb:
            return True

        epoch_count = self._count_entries()
        return epoch_count >= self.snapshot_interval

    def prune_and_archive(self) -> LedgerSummary:
        """
        Main pruning operation:
          1. Verify chain integrity (raises LedgerIntegrityError if broken)
          2. Load all entries
          3. Compute split point: keep last RETENTION_EPOCHS, archive the rest
          4. Compute Root State Hash (checkpoint_hash) over archived entries
          5. Compress archived entries into data/archives/epoch_XXXXXX.jsonl.gz
          6. Rewrite active ledger with retained entries
          7. Update ledger_state.json with checkpoint_hash and tail hashes
          8. Verify chain integrity after operation
          9. Return LedgerSummary
        """
        if not self.ledger_path.exists():
            raise FileNotFoundError(f"Ledger not found: {self.ledger_path}")

        size_before_mb = self.ledger_path.stat().st_size / (1024 * 1024)

        # Step 1: Verify chain before pruning
        chain_ok = self.verify_chain()
        if not chain_ok:
            raise LedgerIntegrityError(
                "LEDGER-CHAIN-0 VIOLATION: Hash chain verification failed before pruning. "
                "Pruning aborted. Investigate evidence ledger for tampering."
            )

        # Step 2: Load all entries
        entries = self._load_entries()
        total = len(entries)

        if total <= self.retention_epochs:
            # Nothing to prune
            return LedgerSummary(
                checkpoint_hash="NO_OP",
                entries_archived=0,
                entries_retained=total,
                archive_file="",
                chain_verified=True,
                ledger_size_before_mb=size_before_mb,
                ledger_size_after_mb=size_before_mb,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        # Step 3: Split
        archive_entries = entries[:total - self.retention_epochs]
        retain_entries  = entries[total - self.retention_epochs:]

        # Step 4: Root State Hash + last-entry bridge hash
        checkpoint_hash = self._compute_checkpoint_hash(archive_entries)
        last_archive_hash = self._last_entry_hash(archive_entries)

        # Step 5: Archive to compressed file
        first_epoch = self._get_epoch_id(archive_entries[0])
        last_epoch  = self._get_epoch_id(archive_entries[-1])
        archive_filename = f"epoch_{first_epoch[:8]}_to_{last_epoch[:8]}.jsonl.gz"
        archive_file = self.archive_dir / archive_filename
        self._write_archive(archive_entries, archive_file)

        # Step 6: Rewrite active ledger
        self._rewrite_ledger(retain_entries)

        # Step 7: Update ledger state
        self._update_state(
            checkpoint_hash=checkpoint_hash,
            last_archive_hash=last_archive_hash,
            archive_file=str(archive_file),
            retained_count=len(retain_entries),
            archived_count=len(archive_entries),
        )

        # Step 8: Verify chain after pruning
        chain_ok_after = self.verify_chain()
        if not chain_ok_after:
            raise LedgerIntegrityError(
                "LEDGER-CHAIN-0 VIOLATION: Hash chain verification failed AFTER pruning. "
                "This is a critical integrity failure. Restore from archive immediately."
            )

        size_after_mb = self.ledger_path.stat().st_size / (1024 * 1024)

        return LedgerSummary(
            checkpoint_hash=checkpoint_hash,
            entries_archived=len(archive_entries),
            entries_retained=len(retain_entries),
            archive_file=str(archive_file),
            chain_verified=True,
            ledger_size_before_mb=size_before_mb,
            ledger_size_after_mb=size_after_mb,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def verify_chain(self) -> bool:
        """
        Walks the active ledger and verifies that each entry's predecessor_hash
        matches the compound_digest of the prior entry.
        Returns True if chain is intact; False if any link is broken.
        """
        entries = self._load_entries()
        if len(entries) <= 1:
            return True

        # Also accept chain continuity from last archived entry hash
        state = self._load_state()
        prior_hash = state.get("last_archive_hash", None)

        for i, entry in enumerate(entries):
            if i == 0 and prior_hash:
                # First entry in pruned ledger: predecessor_hash must match checkpoint
                epoch_ev = entry.get("epoch_evidence", {})
                if epoch_ev.get("predecessor_hash") != prior_hash:
                    return False
            elif i > 0:
                prev = entries[i - 1]
                prev_hash = hashlib.sha256(
                    json.dumps(prev, sort_keys=True, default=str).encode()
                ).hexdigest()
                epoch_ev = entry.get("epoch_evidence", {})
                if epoch_ev.get("predecessor_hash") != prev_hash:
                    return False
        return True

    def get_tail_hashes(self, n: int = 100) -> list[str]:
        """
        Returns the last N compound_digests from the active ledger.
        Used for fast light-client verification without reading full history.
        """
        entries = self._load_entries()
        tail = entries[-n:] if len(entries) >= n else entries
        return [
            e.get("compound_digest", "")
            for e in tail
        ]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_entries(self) -> list[dict]:
        entries = []
        if not self.ledger_path.exists():
            return entries
        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return entries

    def _count_entries(self) -> int:
        if not self.ledger_path.exists():
            return 0
        count = 0
        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count

    def _compute_checkpoint_hash(self, entries: list[dict]) -> str:
        """SHA-256 of all archived entries serialized deterministically."""
        hasher = hashlib.sha256()
        for entry in entries:
            hasher.update(json.dumps(entry, sort_keys=True, default=str).encode())
        return hasher.hexdigest()

    def _last_entry_hash(self, entries: list[dict]) -> str:
        """
        SHA-256 of the last archived entry JSON line.
        This is what the first retained entry's predecessor_hash was set to,
        so it serves as the chain bridge after pruning.
        """
        last_line = json.dumps(entries[-1], sort_keys=True, default=str)
        return hashlib.sha256(last_line.encode()).hexdigest()

    def _get_epoch_id(self, entry: dict) -> str:
        return entry.get("epoch_evidence", {}).get("epoch_id", "unknown")

    def _write_archive(self, entries: list[dict], path: Path) -> None:
        """Write entries as gzip-compressed JSONL."""
        with gzip.open(str(path), "wt", encoding="utf-8") as gz:
            for entry in entries:
                gz.write(json.dumps(entry, sort_keys=True, default=str) + "\n")

    def _rewrite_ledger(self, entries: list[dict]) -> None:
        """Atomically rewrite active ledger with retained entries."""
        tmp_path = self.ledger_path.with_suffix(".adaad_tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
        tmp_path.rename(self.ledger_path)

    def _update_state(
        self,
        checkpoint_hash: str,
        last_archive_hash: str,
        archive_file: str,
        retained_count: int,
        archived_count: int,
    ) -> None:
        """Update the light-state JSON with current checkpoint and tail."""
        state = self._load_state()
        state.update({
            "checkpoint_hash": checkpoint_hash,
            "last_archive_hash": last_archive_hash,
            "last_archive_file": archive_file,
            "retained_count": retained_count,
            "total_archived_to_date": state.get("total_archived_to_date", 0) + archived_count,
            "last_pruned_at": datetime.now(timezone.utc).isoformat(),
            "tail_hashes": self.get_tail_hashes(100),
        })
        tmp_path = self.state_path.with_suffix(".adaad_tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
        tmp_path.rename(self.state_path)

    def _load_state(self) -> dict:
        if self.state_path.exists():
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
