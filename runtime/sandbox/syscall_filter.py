# SPDX-License-Identifier: Apache-2.0
"""Deterministic syscall allowlist checks for sandbox execution."""

from __future__ import annotations

from typing import Iterable, Tuple

from runtime.governance.foundation import sha256_prefixed_digest


def syscall_trace_fingerprint(observed: Iterable[str]) -> str:
    """Return a deterministic fingerprint for observed syscall telemetry.

    The fingerprint is intentionally computed from a canonicalized representation
    (sorted unique syscall names) so that equivalent traces with different input
    ordering produce the same hash.
    """

    canonical_trace = tuple(sorted({str(item) for item in observed}))
    return sha256_prefixed_digest(canonical_trace)


def enforce_syscall_allowlist_with_fingerprint(
    observed: Iterable[str], allowlist: Tuple[str, ...]
) -> tuple[bool, tuple[str, ...], str]:
    """Enforce syscall policy and return a canonical trace fingerprint.

    Invariants:
    - `denied` is a deterministic sorted tuple.
    - `fingerprint` is deterministic for semantically equivalent traces.
    """

    observed_tuple = tuple(str(item) for item in observed)
    allowed = set(allowlist)
    denied = tuple(sorted({item for item in observed_tuple if item not in allowed}))
    return (len(denied) == 0, denied, syscall_trace_fingerprint(observed_tuple))


def enforce_syscall_allowlist(observed: Iterable[str], allowlist: Tuple[str, ...]) -> tuple[bool, tuple[str, ...]]:
    ok, denied, _ = enforce_syscall_allowlist_with_fingerprint(observed, allowlist)
    return (ok, denied)


__all__ = ["enforce_syscall_allowlist", "enforce_syscall_allowlist_with_fingerprint", "syscall_trace_fingerprint"]
