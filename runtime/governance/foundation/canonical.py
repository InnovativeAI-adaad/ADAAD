# SPDX-License-Identifier: Apache-2.0
"""Canonical JSON serialization utilities for deterministic governance paths."""

from __future__ import annotations

import json
from typing import Any


def canonical_json(payload: Any) -> str:
    """Return canonical JSON text for a payload.

    Canonical form is stable across runs: sorted keys, compact separators,
    and UTF-8-safe unicode output.
    """

    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_json_bytes(payload: Any) -> bytes:
    """Return UTF-8 encoded canonical JSON bytes for a payload."""

    return canonical_json(payload).encode("utf-8")


__all__ = ["canonical_json", "canonical_json_bytes"]
