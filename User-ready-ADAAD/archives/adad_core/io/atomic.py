# SPDX-License-Identifier: Apache-2.0
"""Atomic file operations for append-only telemetry.

These helpers avoid partial writes by using temporary files and
ensure parent directories exist before writing.
"""
from __future__ import annotations

from pathlib import Path
import json
import os
import tempfile
from typing import Any


def write_atomic_json(path: Path, obj: Any) -> None:
    """Write ``obj`` to ``path`` atomically.

    The object is serialized with ``json.dump`` and then swapped into
    place using ``os.replace`` to avoid partial writes if the process
    stops unexpectedly.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, path)
    finally:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass


def append_jsonl(path: Path, obj: Any) -> None:
    """Append one JSON object per line to ``path``.

    The parent directory is created if it does not already exist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, default=str) + "\n")
