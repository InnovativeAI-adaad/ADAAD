# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

from runtime.governance.gate_certifier import GateCertifier


def test_forbidden_tokens_rejected(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "bad.py"
    target.write_text("import os\nos.system('rm -rf /')\n", encoding="utf-8")
    monkeypatch.setattr("security.cryovant.verify_session", lambda token: True)
    cert = GateCertifier().certify(target, {"cryovant_token": "x" * 24})
    assert cert["passed"] is False
    assert cert["checks"]["token_ok"] is False


def test_banned_imports_rejected(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "bad_import.py"
    target.write_text("import subprocess\n", encoding="utf-8")
    monkeypatch.setattr("security.cryovant.verify_session", lambda token: True)
    cert = GateCertifier().certify(target, {"cryovant_token": "y" * 24})
    assert cert["passed"] is False
    assert cert["checks"]["import_ok"] is False


def test_token_required(tmp_path: Path) -> None:
    target = tmp_path / "ok.py"
    target.write_text("print('ok')\n", encoding="utf-8")
    cert = GateCertifier().certify(target, {"cryovant_token": "short"})
    assert cert["passed"] is False
    assert cert["checks"]["auth_ok"] is False


def test_token_redacted(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "ok2.py"
    target.write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setattr("security.cryovant.verify_session", lambda token: True)
    cert = GateCertifier().certify(target, {"cryovant_token": "SENSITIVE"})
    assert cert["passed"] is True
    assert "cryovant_token" not in cert.get("metadata", {})
