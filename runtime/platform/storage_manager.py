# SPDX-License-Identifier: Apache-2.0
"""Storage footprint management for ADAAD runtime data."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path


class StorageManager:
    def __init__(self, data_root: Path, max_storage_mb: float = 5000.0):
        self.data_root = data_root
        self.max_storage_mb = max_storage_mb

    def check_and_prune(self) -> dict:
        current_mb = self._get_usage_mb()
        if current_mb < self.max_storage_mb:
            return {"pruned": False, "current_mb": round(current_mb, 3)}

        pruned_count = self._prune_failed_candidates()
        current_mb = self._get_usage_mb()
        if current_mb >= self.max_storage_mb:
            pruned_count += self._prune_old_snapshots()

        return {
            "pruned": True,
            "pruned_count": pruned_count,
            "current_mb": round(self._get_usage_mb(), 3),
        }

    def _get_usage_mb(self) -> float:
        total_bytes = 0
        if not self.data_root.exists():
            return 0.0
        for path in self.data_root.rglob("*"):
            if path.is_file():
                total_bytes += path.stat().st_size
        return total_bytes / (1024.0 * 1024.0)

    def _prune_failed_candidates(self) -> int:
        candidates_dir = self.data_root / "candidates"
        if not candidates_dir.exists():
            return 0
        pruned = 0
        for candidate in candidates_dir.glob("*"):
            if not candidate.is_dir():
                continue
            fitness_file = candidate / "fitness.json"
            if not fitness_file.exists():
                continue
            try:
                fitness = json.loads(fitness_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if float(fitness.get("score", 1.0)) < 0.3:
                shutil.rmtree(candidate, ignore_errors=True)
                pruned += 1
        return pruned

    def _prune_old_snapshots(self) -> int:
        snapshots_dir = self.data_root / "snapshots"
        if not snapshots_dir.exists():
            return 0
        threshold = time.time() - (30 * 24 * 60 * 60)
        pruned = 0
        for snapshot in snapshots_dir.glob("*"):
            try:
                if snapshot.stat().st_mtime < threshold:
                    if snapshot.is_dir():
                        shutil.rmtree(snapshot, ignore_errors=True)
                    else:
                        snapshot.unlink(missing_ok=True)
                    pruned += 1
            except Exception:
                continue
        return pruned


__all__ = ["StorageManager"]
