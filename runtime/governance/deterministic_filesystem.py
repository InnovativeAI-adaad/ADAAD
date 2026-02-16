# SPDX-License-Identifier: Apache-2.0
"""Deterministic filesystem operations for replay consistency."""

from __future__ import annotations

import fnmatch
import glob
import os
from pathlib import Path
from typing import Iterator

from runtime.governance.deterministic_envelope import EntropySource, charge_entropy


def listdir_deterministic(path: str | Path) -> list[str]:
    charge_entropy(EntropySource.FILESYSTEM, f"listdir:{path}")
    return sorted(os.listdir(path))


def walk_deterministic(path: str | Path) -> Iterator[tuple[str, list[str], list[str]]]:
    charge_entropy(EntropySource.FILESYSTEM, f"walk:{path}")
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames.sort()
        filenames.sort()
        yield dirpath, dirnames, filenames


def glob_deterministic(pattern: str) -> list[str]:
    charge_entropy(EntropySource.FILESYSTEM, f"glob:{pattern}")
    return sorted(glob.glob(pattern))


def canonical_path(path: str | Path) -> str:
    return os.path.realpath(os.path.abspath(str(path)))


def read_file_deterministic(path: str | Path, encoding: str = "utf-8") -> str:
    charge_entropy(EntropySource.FILESYSTEM, f"read:{path}")
    with open(path, "r", encoding=encoding, newline=None) as handle:
        return handle.read()


def find_files_deterministic(
    root: str | Path,
    pattern: str = "*",
    exclude_dirs: set[str] | None = None,
) -> list[str]:
    excluded = exclude_dirs or {".git", "__pycache__", ".venv", "node_modules"}
    matches: list[str] = []

    for dirpath, dirnames, filenames in walk_deterministic(root):
        dirnames[:] = [name for name in dirnames if name not in excluded]
        for filename in filenames:
            if fnmatch.fnmatch(filename, pattern):
                matches.append(os.path.join(dirpath, filename))

    return sorted(matches)


__all__ = [
    "listdir_deterministic",
    "walk_deterministic",
    "glob_deterministic",
    "canonical_path",
    "read_file_deterministic",
    "find_files_deterministic",
]
