# SPDX-License-Identifier: Apache-2.0
"""Deterministic checkpoint digest helpers for evolution epochs."""

from __future__ import annotations

from runtime.governance.foundation.hashing import sha256_prefixed_digest


def checkpoint_digest(payload: dict[str, object]) -> str:
    """Return canonical checkpoint digest in ``sha256:<hex>`` format."""

    return sha256_prefixed_digest(payload)


__all__ = ["checkpoint_digest"]
