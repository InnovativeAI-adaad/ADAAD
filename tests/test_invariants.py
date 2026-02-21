# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from runtime import invariants


def test_scan_absolute_paths_ignores_virtualenv_dirs(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "app").mkdir(parents=True)
    (tmp_path / "runtime").mkdir(parents=True)
    (tmp_path / "security").mkdir(parents=True)
    (tmp_path / "security" / "ledger").mkdir(parents=True)
    (tmp_path / "security" / "keys").mkdir(parents=True)
    (tmp_path / ".venv" / "lib").mkdir(parents=True)

    virtualenv_abs_path = "/sto" + "rage/emulated/0/Documents"
    (tmp_path / ".venv" / "lib" / "bad.py").write_text(f'PATH = "{virtualenv_abs_path}"\n', encoding="utf-8")
    (tmp_path / "app" / "good.py").write_text("VALUE = 1\n", encoding="utf-8")

    monkeypatch.setattr(invariants, "ROOT_DIR", tmp_path)

    ok, failures = invariants.scan_absolute_paths()
    assert ok is True
    assert failures == []


def test_scan_banned_imports_ignores_virtualenv_dirs(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "app").mkdir(parents=True)
    (tmp_path / ".venv" / "lib").mkdir(parents=True)

    (tmp_path / ".venv" / "lib" / "bad_import.py").write_text("import core\n", encoding="utf-8")
    (tmp_path / "app" / "good_import.py").write_text("import json\n", encoding="utf-8")

    monkeypatch.setattr(invariants, "ROOT_DIR", tmp_path)

    ok, failures = invariants.scan_banned_imports()
    assert ok is True
    assert failures == []
