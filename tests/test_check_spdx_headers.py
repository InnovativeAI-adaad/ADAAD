# SPDX-License-Identifier: Apache-2.0
"""Regression tests for exact Python SPDX header enforcement."""
from __future__ import annotations

from pathlib import Path

from scripts.check_spdx_headers import SPDX_LINE, _fix_file, _has_spdx


def _write_python(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "candidate.py"
    path.write_text(content, encoding="utf-8")
    return path


def test_has_spdx_accepts_exact_apache_header_in_allowed_window(tmp_path: Path) -> None:
    path = _write_python(
        tmp_path,
        "#!/usr/bin/env python3\n"
        "# coding: utf-8\n"
        f"{SPDX_LINE}\n"
        "print('ok')\n",
    )

    assert _has_spdx(path) is True


def test_has_spdx_rejects_mit_identifier(tmp_path: Path) -> None:
    path = _write_python(
        tmp_path,
        "# SPDX-License-Identifier: MIT\n"
        "print('not allowed')\n",
    )

    assert _has_spdx(path) is False


def test_has_spdx_rejects_non_exact_apache_line(tmp_path: Path) -> None:
    path = _write_python(
        tmp_path,
        "# SPDX-License-Identifier: Apache-2.0 OR MIT\n"
        "print('not allowed')\n",
    )

    assert _has_spdx(path) is False


def test_has_spdx_rejects_exact_header_outside_allowed_window(tmp_path: Path) -> None:
    path = _write_python(
        tmp_path,
        "\n".join(["# filler"] * 6 + [SPDX_LINE, "print('too late')"]) + "\n",
    )

    assert _has_spdx(path) is False


def test_fix_file_replaces_conflicting_spdx_identifier(tmp_path: Path) -> None:
    path = _write_python(
        tmp_path,
        "#!/usr/bin/env python3\n"
        "# SPDX-License-Identifier: MIT\n"
        "print('repair')\n",
    )

    _fix_file(path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[1] == SPDX_LINE
    assert "# SPDX-License-Identifier: MIT" not in lines
    assert _has_spdx(path) is True


def test_main_scans_explicit_file_path(tmp_path: Path, monkeypatch, capsys) -> None:
    path = _write_python(
        tmp_path,
        "# SPDX-License-Identifier: MIT\n"
        "print('explicit file')\n",
    )

    import scripts.check_spdx_headers as check_spdx_headers

    monkeypatch.setattr(check_spdx_headers.sys, "argv", ["check_spdx_headers.py", str(path)])

    assert check_spdx_headers.main() == 1
    assert "candidate.py" in capsys.readouterr().out
