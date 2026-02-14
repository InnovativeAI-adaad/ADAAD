# SPDX-License-Identifier: Apache-2.0
"""Filesystem write-path allowlist checks."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Iterable, Tuple


def _normalize(path: str) -> str:
    return str(PurePosixPath(path))


def enforce_write_path_allowlist(observed_paths: Iterable[str], allowlist: Tuple[str, ...]) -> tuple[bool, tuple[str, ...]]:
    normalized_allow = tuple(_normalize(item) for item in allowlist)
    violations: list[str] = []
    for path in observed_paths:
        norm = _normalize(str(path))
        if not any(norm == item or norm.startswith(f"{item}/") for item in normalized_allow):
            violations.append(norm)
    return (len(violations) == 0, tuple(sorted(set(violations))))


__all__ = ["enforce_write_path_allowlist"]
