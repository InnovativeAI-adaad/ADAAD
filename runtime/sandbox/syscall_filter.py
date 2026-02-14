# SPDX-License-Identifier: Apache-2.0
"""Deterministic syscall allowlist checks for sandbox execution."""

from __future__ import annotations

from typing import Iterable, Tuple


def enforce_syscall_allowlist(observed: Iterable[str], allowlist: Tuple[str, ...]) -> tuple[bool, tuple[str, ...]]:
    allowed = set(allowlist)
    denied = tuple(sorted({str(item) for item in observed if str(item) not in allowed}))
    return (len(denied) == 0, denied)


__all__ = ["enforce_syscall_allowlist"]
