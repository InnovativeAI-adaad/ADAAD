# SPDX-License-Identifier: Apache-2.0
"""Deterministic hashing helpers for canonical governance payloads."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from runtime.governance.foundation.canonical import canonical_json_bytes


def sha256_digest(payload: bytes | bytearray | str | Any) -> str:
    """Return sha256 hex digest.

    Accepts bytes/str directly, and canonicalizes structured payloads.
    """

    if isinstance(payload, (bytes, bytearray)):
        material = bytes(payload)
    elif isinstance(payload, str):
        material = payload.encode("utf-8")
    else:
        material = canonical_json_bytes(payload)
    return sha256(material).hexdigest()


def sha256_prefixed_digest(payload: bytes | bytearray | str | Any) -> str:
    """Return digest prefixed as ``sha256:<hex>``."""

    return f"sha256:{sha256_digest(payload)}"


ZERO_HASH = "sha256:" + ("0" * 64)


__all__ = ["sha256_digest", "sha256_prefixed_digest", "ZERO_HASH"]
