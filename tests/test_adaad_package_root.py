# SPDX-License-Identifier: Apache-2.0
"""Regression tests for the public adaad package root."""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from types import ModuleType

import pytest

import adaad


def test_package_root_preserves_version_exports_and_lazy_loader() -> None:
    """A version-only overwrite must not remove root exports or lazy imports."""

    assert re.fullmatch(r"\d+\.\d+\.\d+", adaad.__version__)
    assert adaad.__version__ == Path("VERSION").read_text(encoding="utf-8").strip()
    assert adaad.APP_ROOT == Path(adaad.__file__).resolve().parent
    assert set(adaad.__all__) == {"APP_ROOT", "core", "orchestrator", "api"}
    assert callable(adaad.__getattr__)


def test_package_root_lazy_loads_declared_subpackages() -> None:
    """Declared root exports should resolve to importable subpackages on demand."""

    for name in ("core", "orchestrator", "api"):
        resolved = getattr(adaad, name)
        assert isinstance(resolved, ModuleType)
        assert resolved is importlib.import_module(f"adaad.{name}")


def test_package_root_rejects_unknown_lazy_attribute() -> None:
    """Unknown package-root attributes should fail with the standard error."""

    with pytest.raises(AttributeError, match="module 'adaad' has no attribute 'missing_root_export'"):
        adaad.__getattr__("missing_root_export")
