# SPDX-License-Identifier: Apache-2.0
"""ADAAD namespace package for core and orchestrator primitives."""

from __future__ import annotations

import importlib
from types import ModuleType

__version__ = "9.75.0"
__all__ = ["core", "orchestrator"]


def __getattr__(name: str) -> ModuleType:
    """Lazily resolve namespace subpackages to avoid import cycles."""
    if name in __all__:
        return importlib.import_module(f"adaad.{name}")
    raise AttributeError(f"module 'adaad' has no attribute {name!r}")
