# SPDX-License-Identifier: Apache-2.0
"""Ledger guardian: automatic recovery and snapshot management."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from runtime import metrics
from runtime.evolution.lineage_v2 import LineageIntegrityError, LineageLedgerV2, LineageRecoveryHook
from security.ledger.journal import JournalIntegrityError, JournalRecoveryHook, verify_journal_integrity


@dataclass(frozen=True)
class SnapshotMetadata:
    snapshot_id: str
    timestamp: str
    file_count: int
    total_bytes: int
    files: dict[str, str]
    epoch_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "files": self.files,
            "epoch_id": self.epoch_id,
        }


class SnapshotManager:
    """Manages rotating snapshots with retention policy and metadata."""

    def __init__(self, snapshot_dir: Path, max_snapshots: int = 10):
        self.snapshot_dir = snapshot_dir
        self.max_snapshots = max_snapshots
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.snapshot_dir / "snapshots.json"
        self._metadata: dict[str, SnapshotMetadata] = {}
        self._load_metadata()

    def _load_metadata(self) -> None:
        if not self.metadata_path.exists():
            return
        try:
            raw = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            for snapshot_id, item in raw.items():
                self._metadata[snapshot_id] = SnapshotMetadata(
                    snapshot_id=snapshot_id,
                    timestamp=str(item.get("timestamp") or ""),
                    file_count=int(item.get("file_count") or 0),
                    total_bytes=int(item.get("total_bytes") or 0),
                    files=dict(item.get("files") or {}),
                    epoch_id=str(item.get("epoch_id") or ""),
                )
        except (ValueError, TypeError):
            self._metadata = {}

    def _save_metadata(self) -> None:
        payload = {sid: meta.to_dict() for sid, meta in self._metadata.items()}
        self.metadata_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def create_snapshot(self, *args: Path | str) -> Path:
        """Create snapshot with backward-compatible signatures.

        Supported signatures:
        - create_snapshot(source_path)
        - create_snapshot(lineage_path, journal_path, epoch_id)
        """
        if len(args) == 1 and isinstance(args[0], Path):
            metadata = self.create_snapshot_set([args[0]])
            return self.snapshot_dir / metadata.snapshot_id / args[0].name
        if len(args) == 3 and isinstance(args[0], Path) and isinstance(args[1], Path) and isinstance(args[2], str):
            metadata = self.create_snapshot_set([args[0], args[1]], epoch_id=args[2])
            return self.snapshot_dir / metadata.snapshot_id
        raise TypeError("create_snapshot expects (source_path) or (lineage_path, journal_path, epoch_id)")

    def create_snapshot_set(self, sources: list[Path], epoch_id: str = "") -> SnapshotMetadata:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snapshot_id = f"snapshot-{timestamp}"
        snapshot_path = self.snapshot_dir / snapshot_id
        snapshot_path.mkdir(parents=True, exist_ok=True)

        file_hashes: dict[str, str] = {}
        total_bytes = 0
        for source in sources:
            source.parent.mkdir(parents=True, exist_ok=True)
            if not source.exists():
                source.touch()
            target = snapshot_path / source.name
            shutil.copy2(source, target)
            file_hashes[source.name] = self._hash_file(target)
            total_bytes += target.stat().st_size

        metadata = SnapshotMetadata(
            snapshot_id=snapshot_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            file_count=len(sources),
            total_bytes=total_bytes,
            files=file_hashes,
            epoch_id=epoch_id,
        )
        self._metadata[snapshot_id] = metadata
        self._save_metadata()
        self._prune_old_snapshots()

        metrics.log(event_type="snapshot_created", payload=metadata.to_dict(), level="INFO")
        return metadata

    def list_snapshots(self) -> list[SnapshotMetadata]:
        return sorted(self._metadata.values(), key=lambda m: m.timestamp, reverse=True)

    def get_latest_snapshot(self) -> SnapshotMetadata | None:
        snapshots = self.list_snapshots()
        return snapshots[0] if snapshots else None

    def restore_snapshot(self, snapshot_id: str, lineage_path: Path, cryovant_path: Path) -> bool:
        metadata = self._metadata.get(snapshot_id)
        if metadata is None:
            metrics.log(event_type="snapshot_restore_failed", payload={"snapshot_id": snapshot_id, "reason": "not_found"}, level="ERROR")
            return False

        snapshot_dir = self.snapshot_dir / snapshot_id
        if not snapshot_dir.exists():
            metrics.log(event_type="snapshot_restore_failed", payload={"snapshot_id": snapshot_id, "reason": "missing_directory"}, level="ERROR")
            return False

        restored_any = False
        for file_name, target_path in ((lineage_path.name, lineage_path), (cryovant_path.name, cryovant_path)):
            source = snapshot_dir / file_name
            if source.exists():
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target_path)
                restored_any = True

        metrics.log(
            event_type="snapshot_restored" if restored_any else "snapshot_restore_failed",
            payload={"snapshot_id": snapshot_id, "restored_any": restored_any},
            level="INFO" if restored_any else "ERROR",
        )
        return restored_any

    def _prune_old_snapshots(self) -> None:
        snapshots = sorted(self._metadata.values(), key=lambda m: m.timestamp, reverse=True)
        for old in snapshots[self.max_snapshots :]:
            shutil.rmtree(self.snapshot_dir / old.snapshot_id, ignore_errors=True)
            self._metadata.pop(old.snapshot_id, None)
        self._save_metadata()

    def get_latest_valid_snapshot(self, source_name: str, validator: Callable[[Path], None]) -> Path | None:
        snapshots = sorted(
            [d for d in self.snapshot_dir.glob("snapshot-*") if d.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for snapshot_dir in snapshots:
            snapshot = snapshot_dir / source_name
            if not snapshot.exists():
                continue
            try:
                validator(snapshot)
                return snapshot
            except Exception:
                continue
        return None

    @staticmethod
    def _hash_file(path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()


class AutoRecoveryHook(LineageRecoveryHook, JournalRecoveryHook):
    """Attempts ledger/journal recovery from latest valid snapshot."""

    def __init__(self, snapshot_manager: SnapshotManager):
        self.snapshot_manager = snapshot_manager
        self.recovery_log: list[dict[str, Any]] = []

    def on_lineage_integrity_failure(self, *, ledger_path: Path, error: LineageIntegrityError) -> None:
        snapshot = self.snapshot_manager.get_latest_valid_snapshot(
            ledger_path.name,
            lambda p: LineageLedgerV2(p).verify_integrity(),
        )
        if snapshot is None:
            raise RuntimeError(f"lineage_recovery_failed:{error}") from error

        self._restore_from_snapshot(target_path=ledger_path, snapshot_path=snapshot, error=str(error), recovery_type="lineage_recovery")

    def on_journal_integrity_failure(self, *, journal_path: Path, error: JournalIntegrityError) -> None:
        snapshot = self.snapshot_manager.get_latest_valid_snapshot(
            journal_path.name,
            lambda p: verify_journal_integrity(journal_path=p),
        )
        if snapshot is None:
            raise RuntimeError(f"journal_recovery_failed:{error}") from error

        self._restore_from_snapshot(target_path=journal_path, snapshot_path=snapshot, error=str(error), recovery_type="journal_recovery")

    def _restore_from_snapshot(self, *, target_path: Path, snapshot_path: Path, error: str, recovery_type: str) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        corrupted_backup = target_path.with_suffix(target_path.suffix + ".corrupted")
        if target_path.exists():
            shutil.move(target_path, corrupted_backup)
        shutil.copy2(snapshot_path, target_path)

        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": recovery_type,
            "error": error,
            "restored_from": str(snapshot_path),
            "corrupted_backup": str(corrupted_backup),
        }
        self.recovery_log.append(event)
        metrics.log(event_type=recovery_type, payload=event, level="WARNING")

    def attempt_recovery(self, lineage_path: Path, cryovant_path: Path, error_type: str) -> dict[str, Any]:
        latest = self.snapshot_manager.get_latest_snapshot()
        if latest is None:
            result = {
                "success": False,
                "reason": "no_snapshots_available",
                "error_type": error_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self.recovery_log.append(result)
            metrics.log(event_type="auto_recovery_failed", payload=result, level="ERROR")
            return result

        success = self.snapshot_manager.restore_snapshot(latest.snapshot_id, lineage_path, cryovant_path)
        result = {
            "success": success,
            "snapshot_id": latest.snapshot_id,
            "snapshot_epoch": latest.epoch_id,
            "error_type": error_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.recovery_log.append(result)
        metrics.log(event_type="auto_recovery_success" if success else "auto_recovery_failed", payload=result, level="WARNING" if success else "ERROR")
        return result

    def get_recovery_history(self) -> list[dict[str, Any]]:
        return list(self.recovery_log)


__all__ = ["SnapshotMetadata", "SnapshotManager", "AutoRecoveryHook"]
