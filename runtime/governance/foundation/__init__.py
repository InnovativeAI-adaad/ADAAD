# SPDX-License-Identifier: Apache-2.0
"""Governance foundation primitives."""

from runtime.governance.foundation.canonical import canonical_json, canonical_json_bytes
from runtime.governance.foundation.clock import now_iso, utc_now_iso, utc_timestamp_label
from runtime.governance.foundation.determinism import (
    RuntimeDeterminismProvider,
    SeededDeterminismProvider,
    SystemDeterminismProvider,
    default_provider,
    require_replay_safe_provider,
)
from runtime.governance.foundation.hashing import ZERO_HASH, sha256_digest, sha256_prefixed_digest
from runtime.governance.foundation.safe_access import coerce_log_entry, require, safe_get, safe_list, safe_str

__all__ = [
    "RuntimeDeterminismProvider",
    "SeededDeterminismProvider",
    "SystemDeterminismProvider",
    "canonical_json",
    "canonical_json_bytes",
    "default_provider",
    "require_replay_safe_provider",
    "sha256_digest",
    "sha256_prefixed_digest",
    "ZERO_HASH",
    "now_iso",
    "utc_now_iso",
    "utc_timestamp_label",
    "safe_get",
    "safe_list",
    "safe_str",
    "require",
    "coerce_log_entry",
]
