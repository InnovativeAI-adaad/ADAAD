# SPDX-License-Identifier: Apache-2.0
"""Optional runtime import guard for strict/test execution modes.

This guard is intentionally opt-in to avoid destabilizing regular runtime imports.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import os
import sys
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class GuardConfig:
    blocked_roots: tuple[str, ...]


class _BlockedImportLoader(importlib.abc.Loader):
    def __init__(self, fullname: str) -> None:
        self._fullname = fullname

    def create_module(self, spec):  # type: ignore[no-untyped-def]
        return None

    def exec_module(self, module):  # type: ignore[no-untyped-def]
        raise ModuleNotFoundError(f"blocked import root in strict mode: {self._fullname}")


class RuntimeImportGuard(importlib.abc.MetaPathFinder):
    def __init__(self, config: GuardConfig) -> None:
        self._blocked_roots = set(config.blocked_roots)

    def find_spec(self, fullname, path=None, target=None):  # type: ignore[no-untyped-def]
        root = fullname.split(".", 1)[0]
        if root not in self._blocked_roots:
            return None
        return importlib.machinery.ModuleSpec(fullname, _BlockedImportLoader(fullname))


def _guard_mode_from_env() -> str:
    explicit_mode = os.getenv("ADAAD_RUNTIME_IMPORT_GUARD", "").strip().lower()
    if explicit_mode:
        return explicit_mode
    replay_mode = os.getenv("ADAAD_REPLAY_MODE", "").strip().lower()
    if replay_mode == "strict":
        return "strict"
    if os.getenv("PYTEST_CURRENT_TEST"):
        return "test"
    return "off"


def _parse_blocked_roots(raw: str | None = None) -> tuple[str, ...]:
    value = raw if raw is not None else os.getenv("ADAAD_BLOCKED_IMPORT_ROOTS", "core,engines,adad_core,ADAAD22")
    return tuple(token.strip() for token in value.split(",") if token.strip())


def install_runtime_import_guard(*, blocked_roots: Sequence[str] | None = None) -> bool:
    mode = _guard_mode_from_env()
    if mode not in {"strict", "test"}:
        return False

    config = GuardConfig(blocked_roots=tuple(blocked_roots) if blocked_roots is not None else _parse_blocked_roots())
    if not config.blocked_roots:
        return False

    for finder in sys.meta_path:
        if isinstance(finder, RuntimeImportGuard):
            return False
    sys.meta_path.insert(0, RuntimeImportGuard(config))
    return True


__all__ = ["RuntimeImportGuard", "install_runtime_import_guard"]
