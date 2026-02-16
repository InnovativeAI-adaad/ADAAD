# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from tools import lint_determinism


def test_lint_determinism_flags_forbidden_dynamic_execution(tmp_path: Path) -> None:
    target = tmp_path / "runtime" / "governance" / "bad.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def run(x):\n    return eval(x)\n", encoding="utf-8")

    issues = lint_determinism._lint_file(target)

    assert issues
    assert any(issue.message == "forbidden_dynamic_execution" for issue in issues)


def test_lint_determinism_flags_importlib_alias_usage(tmp_path: Path) -> None:
    target = tmp_path / "runtime" / "evolution" / "bad_alias.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("import importlib as il\n\ndef run():\n    return il.import_module('json')\n", encoding="utf-8")

    issues = lint_determinism._lint_file(target)

    assert issues
    assert any(issue.message == "forbidden_dynamic_execution" for issue in issues)


def test_lint_determinism_flags_from_import_alias_usage(tmp_path: Path) -> None:
    target = tmp_path / "security" / "bad_from_alias.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("from importlib import import_module as im\n\ndef run():\n    return im('json')\n", encoding="utf-8")

    issues = lint_determinism._lint_file(target)

    assert issues
    assert any(issue.message == "forbidden_dynamic_execution" for issue in issues)


def test_lint_determinism_flags_entropy_calls_in_governance_scope(tmp_path: Path) -> None:
    target = tmp_path / "runtime" / "governance" / "entropy.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "import time\nfrom datetime import datetime\n\ndef run():\n    return time.time(), datetime.now()\n",
        encoding="utf-8",
    )

    issues = lint_determinism._lint_file(target)

    assert issues
    assert any(issue.message == "forbidden_entropy_source" for issue in issues)


def test_lint_determinism_flags_entropy_imports_in_evolution_scope(tmp_path: Path) -> None:
    target = tmp_path / "runtime" / "evolution" / "entropy_import.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("import random\n", encoding="utf-8")

    issues = lint_determinism._lint_file(target)

    assert issues
    assert any(issue.message == "forbidden_entropy_import" for issue in issues)


def test_lint_determinism_accepts_clean_file(tmp_path: Path) -> None:
    target = tmp_path / "runtime" / "evolution" / "good.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def run(x):\n    return x + 1\n", encoding="utf-8")

    issues = lint_determinism._lint_file(target)

    assert issues == []
