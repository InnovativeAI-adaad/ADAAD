# SPDX-License-Identifier: Apache-2.0
"""Deterministic resource quota checks for sandbox execution."""

from __future__ import annotations

from typing import Dict


def enforce_resource_quotas(*, observed_cpu_s: float, observed_memory_mb: float, observed_disk_mb: float, observed_duration_s: float, cpu_limit_s: int, memory_limit_mb: int, disk_limit_mb: int, timeout_s: int) -> Dict[str, object]:
    cpu_ok = float(observed_cpu_s) <= float(cpu_limit_s)
    memory_ok = float(observed_memory_mb) <= float(memory_limit_mb)
    disk_ok = float(observed_disk_mb) <= float(disk_limit_mb)
    timeout_ok = float(observed_duration_s) <= float(timeout_s)
    passed = bool(cpu_ok and memory_ok and disk_ok and timeout_ok)
    return {
        "passed": passed,
        "cpu_ok": cpu_ok,
        "memory_ok": memory_ok,
        "disk_ok": disk_ok,
        "timeout_ok": timeout_ok,
        "observed": {
            "cpu_s": round(float(observed_cpu_s), 4),
            "memory_mb": round(float(observed_memory_mb), 4),
            "disk_mb": round(float(observed_disk_mb), 4),
            "duration_s": round(float(observed_duration_s), 4),
        },
    }


__all__ = ["enforce_resource_quotas"]
