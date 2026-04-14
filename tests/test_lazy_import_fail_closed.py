# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import importlib

import pytest

import app.main as app_main
import server
from ui import aponi_dashboard


def test_server_lazy_import_failure_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import_module = importlib.import_module

    def _fail_runtime_metrics_analysis(name: str, package: str | None = None):
        if name == "runtime.metrics_analysis":
            raise ModuleNotFoundError("No module named runtime.metrics_analysis", name=name)
        return real_import_module(name, package)

    monkeypatch.setattr(server.importlib, "import_module", _fail_runtime_metrics_analysis)
    server._LAZY_IMPORT_CACHE.clear()

    with pytest.raises(RuntimeError, match=r"lazy_init_failed:runtime\.metrics_analysis\.rolling_determinism_score"):
        server.rolling_determinism_score()


def test_ui_lazy_import_failure_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import_module = importlib.import_module

    def _fail_runtime_evolution(name: str, package: str | None = None):
        if name == "runtime.evolution":
            raise ModuleNotFoundError("No module named runtime.evolution", name=name)
        return real_import_module(name, package)

    monkeypatch.setattr(aponi_dashboard.importlib, "import_module", _fail_runtime_evolution)
    aponi_dashboard._LAZY_IMPORT_CACHE.clear()

    with pytest.raises(RuntimeError, match=r"lazy_init_failed:runtime\.evolution\.LineageLedgerV2"):
        aponi_dashboard.LineageLedgerV2()


def test_app_main_lazy_dashboard_import_failure_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import_module = importlib.import_module

    def _fail_dashboard(name: str, package: str | None = None):
        if name == "ui.aponi_dashboard":
            raise ModuleNotFoundError("No module named ui.aponi_dashboard", name=name)
        return real_import_module(name, package)

    monkeypatch.setattr(app_main.importlib, "import_module", _fail_dashboard)

    with pytest.raises(RuntimeError, match=r"lazy_init_failed:ui\.aponi_dashboard\.AponiDashboard"):
        app_main._build_aponi_dashboard()
