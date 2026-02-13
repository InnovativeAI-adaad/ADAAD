# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from runtime.platform.android_monitor import AndroidMonitor, ResourceSnapshot


def test_resource_snapshot_flags() -> None:
    snap = ResourceSnapshot(battery_percent=10.0, memory_mb=2000.0, storage_mb=5000.0, cpu_percent=10.0)
    assert snap.is_constrained()
    assert snap.should_throttle()


def test_android_monitor_snapshot_non_android(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(AndroidMonitor, "_detect_android", staticmethod(lambda: False))
    monitor = AndroidMonitor(tmp_path)
    snapshot = monitor.snapshot()
    assert snapshot.battery_percent == 100.0
    assert snapshot.storage_mb >= 0.0
