# SPDX-License-Identifier: Apache-2.0
"""Cryovant identity helpers for deterministic source hashing."""

from __future__ import annotations

import hashlib
import importlib
import inspect
from pathlib import Path
from types import ModuleType
from typing import Any


def _read_module_source(module: ModuleType) -> str:
    source_file = getattr(module, "__file__", None)
    if source_file:
        source_path = Path(source_file)
        if source_path.suffix in {".pyc", ".pyo"}:
            source_path = source_path.with_suffix(".py")
        if source_path.exists():
            return source_path.read_text(encoding="utf-8")
    return inspect.getsource(module)


def _normalize_source(source: str) -> str:
    return source.replace("\r\n", "\n").replace("\r", "\n")


def deterministic_source_hash(module: ModuleType | str | Path) -> str:
    """Return deterministic sha256 digest for Python source."""
    if isinstance(module, str):
        module_obj = importlib.import_module(module)
    elif isinstance(module, Path):
        raw = module.read_text(encoding="utf-8")
        return hashlib.sha256(_normalize_source(raw).encode("utf-8")).hexdigest()
    else:
        module_obj = module

    source = _read_module_source(module_obj)
    return hashlib.sha256(_normalize_source(source).encode("utf-8")).hexdigest()


def build_identity(module: ModuleType | str | Path, tool_id: str, version: str) -> dict[str, Any]:
    """Build deterministic tool identity payload for manifest emission."""
    return {
        "tool_id": str(tool_id),
        "version": str(version),
        "hash": deterministic_source_hash(module),
    }


__all__ = ["build_identity", "deterministic_source_hash"]
