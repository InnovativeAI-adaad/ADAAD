# SPDX-License-Identifier: Apache-2.0

import json
import time
from pathlib import Path

from runtime.platform.storage_manager import StorageManager


def test_storage_manager_prunes_failed_candidates(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates"
    low = candidates / "low"
    low.mkdir(parents=True)
    (low / "fitness.json").write_text(json.dumps({"score": 0.1}), encoding="utf-8")

    mgr = StorageManager(tmp_path, max_storage_mb=0.0)
    result = mgr.check_and_prune()
    assert result["pruned"]
    assert not low.exists()


def test_storage_manager_prunes_old_snapshots(tmp_path: Path) -> None:
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir(parents=True)
    old = snapshots / "old.snap"
    old.write_text("x", encoding="utf-8")
    old_ts = time.time() - (40 * 24 * 60 * 60)
    old.chmod(0o644)
    import os
    os.utime(old, (old_ts, old_ts))

    mgr = StorageManager(tmp_path, max_storage_mb=0.0)
    mgr.check_and_prune()
    assert not old.exists()
