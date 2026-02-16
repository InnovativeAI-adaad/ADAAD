# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib

from runtime.import_guard import RuntimeImportGuard, install_runtime_import_guard


def _remove_runtime_guards() -> None:
    import sys

    sys.meta_path = [finder for finder in sys.meta_path if not isinstance(finder, RuntimeImportGuard)]


def test_import_guard_disabled_by_default(monkeypatch) -> None:
    _remove_runtime_guards()
    monkeypatch.delenv("ADAAD_RUNTIME_IMPORT_GUARD", raising=False)
    monkeypatch.delenv("ADAAD_REPLAY_MODE", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    installed = install_runtime_import_guard(blocked_roots=("blocked_root",))

    assert installed is False


def test_import_guard_blocks_in_strict_mode(monkeypatch) -> None:
    _remove_runtime_guards()
    monkeypatch.setenv("ADAAD_RUNTIME_IMPORT_GUARD", "strict")

    installed = install_runtime_import_guard(blocked_roots=("blocked_root",))

    assert installed is True
    try:
        try:
            importlib.import_module("blocked_root")
            assert False, "expected blocked import"
        except ModuleNotFoundError as exc:
            assert "blocked import root in strict mode" in str(exc)
    finally:
        _remove_runtime_guards()
