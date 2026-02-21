# SPDX-License-Identifier: Apache-2.0
"""Cryovant-compatible deterministic identity payload for tools."""

from __future__ import annotations

import datetime as _dt
import hashlib
import inspect
from types import ModuleType


def compute_source_hash(module: ModuleType) -> str:
    """Compute SHA256 hash from module source text."""
    try:
        source = inspect.getsource(module)
    except (OSError, TypeError):
        source = repr(module)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def build_identity(module: ModuleType, tool_id: str, version: str) -> dict[str, str]:
    """Build deterministic identity payload for registry + manifest usage."""
    return {
        "tool_id": tool_id,
        "version": version,
        "hash": compute_source_hash(module),
        "timestamp": _dt.datetime.now(_dt.UTC).isoformat().replace("+00:00", "Z"),
    }
