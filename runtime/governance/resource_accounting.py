# SPDX-License-Identifier: Apache-2.0
"""Deterministic resource accounting helpers shared across governance and sandboxing."""

from __future__ import annotations

from typing import Any, Mapping


def _parse_non_negative(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if parsed < 0:
        return 0.0
    return parsed


def normalize_resource_usage_snapshot(
    *,
    cpu_seconds: Any = 0.0,
    memory_mb: Any = 0.0,
    wall_seconds: Any = 0.0,
    disk_mb: Any = 0.0,
) -> dict[str, float]:
    """Return a canonical usage snapshot with stable rounding and aliases."""

    normalized = {
        "cpu_seconds": round(_parse_non_negative(cpu_seconds), 4),
        "memory_mb": round(_parse_non_negative(memory_mb), 4),
        "wall_seconds": round(_parse_non_negative(wall_seconds), 4),
        "disk_mb": round(_parse_non_negative(disk_mb), 4),
    }
    normalized["duration_s"] = normalized["wall_seconds"]
    return normalized


def coalesce_resource_usage_snapshot(*, observed: Mapping[str, Any], telemetry: Mapping[str, Any]) -> dict[str, float]:
    """Resolve deterministic resource usage by taking maxima across trusted aliases."""

    memory_mb = max(
        _parse_non_negative(observed.get("peak_rss_mb")),
        _parse_non_negative(observed.get("memory_mb")),
        _parse_non_negative(telemetry.get("memory_mb")),
    )
    cpu_seconds = max(
        _parse_non_negative(observed.get("cpu_seconds")),
        _parse_non_negative(observed.get("cpu_time_seconds")),
    )
    wall_seconds = max(
        _parse_non_negative(observed.get("wall_seconds")),
        _parse_non_negative(observed.get("wall_time_seconds")),
        _parse_non_negative(observed.get("duration_s")),
    )
    disk_mb = _parse_non_negative(observed.get("disk_mb"))
    return normalize_resource_usage_snapshot(
        cpu_seconds=cpu_seconds,
        memory_mb=memory_mb,
        wall_seconds=wall_seconds,
        disk_mb=disk_mb,
    )


__all__ = ["coalesce_resource_usage_snapshot", "normalize_resource_usage_snapshot"]
