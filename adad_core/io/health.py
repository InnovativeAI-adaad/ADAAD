"""Lightweight system health checks.

Designed to run on constrained Android environments where only a subset
of system utilities are available.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional


def battery_percentage() -> Optional[int]:
    """Best-effort battery percentage.

    On Android/Termux, ``dumpsys battery`` is the most common source. If
    it is unavailable the function returns ``None``.
    """
    dumpsys = shutil.which("dumpsys")
    if not dumpsys:
        return None
    try:
        proc = subprocess.run([dumpsys, "battery"], check=True, capture_output=True, text=True)
    except Exception:
        return None
    for line in proc.stdout.splitlines():
        if "level" in line.lower():
            try:
                return int(line.split(":", 1)[1].strip())
            except Exception:
                return None
    return None


def battery_allows_run(min_percent: int = 15) -> bool:
    """Return ``True`` if the battery level is acceptable.

    When the battery percentage cannot be determined, the function errs
    on the side of permissive to avoid blocking execution in offline
    development environments.
    """
    level = battery_percentage()
    if level is None:
        return True
    return level >= min_percent


def over_cpu_limit(load_factor: float = 1.0) -> bool:
    """Check whether the system load average is above the CPU budget."""
    try:
        with open("/proc/loadavg", "r", encoding="utf-8") as f:
            load = float(f.read().split()[0])
        cpu_count = os.cpu_count() or 1
        return load > cpu_count * load_factor
    except Exception:
        return False


def health_snapshot() -> dict:
    """Return a quick snapshot suitable for logging or debug output."""
    return {
        "battery": battery_percentage(),
        "over_cpu_limit": over_cpu_limit(),
    }
