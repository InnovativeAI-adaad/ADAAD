# SPDX-License-Identifier: Apache-2.0

"""
Module: test_nexus_setup
Purpose: Validate nexus_setup validate-only execution and CLI contract behavior.
Author: ADAAD / InnovativeAI-adaad
Integration points:
  - Imports from: nexus_setup
  - Consumed by: pytest
  - Governance impact: low — setup validation safety checks
"""

from __future__ import annotations

import json

import pytest

import nexus_setup


def test_validate_only_json_report_and_exit_code(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    report = {
        "checks": [{"name": "python_version", "status": "fail", "detail": "bad"}],
        "overall": "fail",
        "required_failed": 1,
        "optional_failed": 0,
    }
    monkeypatch.setattr(nexus_setup, "_run_validation", lambda: report)

    exit_code = nexus_setup.main(["--validate-only", "--json"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == report


def test_validate_only_does_not_run_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"setup": False}

    def _never_called() -> None:
        called["setup"] = True

    monkeypatch.setattr(nexus_setup, "bootstrap_he65_nexus", _never_called)
    monkeypatch.setattr(
        nexus_setup,
        "_run_validation",
        lambda: {
            "checks": [],
            "overall": "pass",
            "required_failed": 0,
            "optional_failed": 0,
        },
    )

    exit_code = nexus_setup.main(["--validate-only"])

    assert exit_code == 0
    assert called["setup"] is False


def test_main_runs_setup_when_required_checks_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"setup": False}

    def _setup() -> None:
        called["setup"] = True

    monkeypatch.setattr(nexus_setup, "bootstrap_he65_nexus", _setup)
    monkeypatch.setattr(
        nexus_setup,
        "_run_validation",
        lambda: {
            "checks": [],
            "overall": "pass",
            "required_failed": 0,
            "optional_failed": 0,
        },
    )

    exit_code = nexus_setup.main([])

    assert exit_code == 0
    assert called["setup"] is True


def test_json_requires_validate_only() -> None:
    with pytest.raises(SystemExit):
        nexus_setup.main(["--json"])


def test_validate_governance_schema_skips_when_schema_files_absent(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(nexus_setup, "ROOT", tmp_path)

    result = nexus_setup._validate_governance_schema()

    assert result["status"] == "pass"
    assert "skipped" in result["detail"]


def test_validate_port_availability_sets_reuseaddr(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"reuseaddr": False}

    class _SocketStub:
        def setsockopt(self, level, optname, value):
            if level == nexus_setup.socket.SOL_SOCKET and optname == nexus_setup.socket.SO_REUSEADDR and value == 1:
                called["reuseaddr"] = True

        def bind(self, _addr):
            return None

        def close(self):
            return None

    monkeypatch.setattr(nexus_setup.socket, "socket", lambda *_args, **_kwargs: _SocketStub())

    report = nexus_setup._validate_port_availability(8000)

    assert called["reuseaddr"] is True
    assert report["status"] == "pass"
