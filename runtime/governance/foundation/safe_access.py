# SPDX-License-Identifier: Apache-2.0
"""
Module: safe_access
Purpose: Provide deterministic null-safe access helpers for governance/state payloads.
Author: ADAAD / InnovativeAI-adaad
Integration points:
  - Imports from: typing
  - Consumed by: runtime/app/tools modules reading mutable JSON payloads
  - Governance impact: low — reduces NoneType propagation risks in governed paths
"""

from __future__ import annotations

from typing import Any


_LOG_ENTRY_KEYS = (
    "id",
    "timestamp",
    "mode",
    "status",
    "mutation_id",
    "lineage_ref",
    "error",
    "metadata",
)


def safe_get(d: dict | None, *keys: str, default: Any = None) -> Any:
    """Safely walk nested dicts and return default on null/non-mapping nodes.

    Note: this intentionally treats a missing key and an explicit ``None`` value the same
    (both return ``default``). Final values of ``0``, ``False``, and ``""`` are preserved.
    """
    current: Any = d
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def safe_list(val: Any, default: list | None = None) -> list:
    """Return a list value when valid, otherwise a deterministic default list."""
    if isinstance(val, list):
        return val
    if default is None:
        return []
    return default


def safe_str(val: Any, default: str = "") -> str:
    """Return string value when valid, otherwise default."""
    if isinstance(val, str):
        return val
    return default


def require(val: Any, field_name: str) -> Any:
    """Require a non-null value for safety-critical fields."""
    if val is None:
        raise ValueError(f"missing_required_field:{field_name}")
    return val


def coerce_log_entry(raw: dict | None) -> dict:
    """Coerce mutable log entries into a fixed, null-safe schema."""
    source = raw if isinstance(raw, dict) else {}
    entry = {
        "id": safe_str(source.get("id")),
        "timestamp": safe_str(source.get("timestamp")),
        "mode": safe_str(source.get("mode")),
        "status": safe_str(source.get("status")),
        "mutation_id": safe_str(source.get("mutation_id")),
        "lineage_ref": safe_str(source.get("lineage_ref")),
        "error": safe_str(source.get("error")),
        "metadata": source.get("metadata") if isinstance(source.get("metadata"), dict) else {},
    }
    return entry


__all__ = ["coerce_log_entry", "require", "safe_get", "safe_list", "safe_str"]
