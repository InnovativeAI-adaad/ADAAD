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


def test_lint_determinism_flags_builtin_open_in_governance_scope(tmp_path: Path) -> None:
    target = tmp_path / "runtime" / "governance" / "fs_open.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "def run(path):\n    with open(path, 'r', encoding='utf-8') as handle:\n        return handle.read()\n",
        encoding="utf-8",
    )

    issues = lint_determinism._lint_file(target)

    assert any(issue.message == "forbidden_nondeterministic_filesystem_api" for issue in issues)


def test_lint_determinism_flags_path_read_text_in_evolution_scope(tmp_path: Path) -> None:
    target = tmp_path / "runtime" / "evolution" / "path_read.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "from pathlib import Path\n\ndef run(path):\n    return Path(path).read_text(encoding='utf-8')\n",
        encoding="utf-8",
    )

    issues = lint_determinism._lint_file(target)

    assert any(issue.message == "forbidden_nondeterministic_filesystem_api" for issue in issues)


def test_lint_determinism_flags_os_and_glob_calls_in_enforced_scope(tmp_path: Path) -> None:
    target = tmp_path / "runtime" / "governance" / "fs_walk.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "import glob\nimport os\n\ndef run(path):\n    return os.listdir(path), list(os.walk(path)), glob.glob('*.py')\n",
        encoding="utf-8",
    )

    issues = lint_determinism._lint_file(target)

    flagged = [issue for issue in issues if issue.message == "forbidden_nondeterministic_filesystem_api"]
    assert len(flagged) == 3


def test_lint_determinism_allows_deterministic_filesystem_wrappers(tmp_path: Path) -> None:
    target = tmp_path / "runtime" / "governance" / "deterministic_filesystem.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        """
import glob
import os
from pathlib import Path


def listdir_deterministic(path):
    return sorted(os.listdir(path))


def walk_deterministic(path):
    return list(os.walk(path))


def glob_deterministic(pattern):
    return sorted(glob.glob(pattern))


def read_file_deterministic(path):
    return open(path, 'r', encoding='utf-8').read()


def find_files_deterministic(path):
    return list(Path(path).glob('**/*.py'))
""".strip()
        + "\n",
        encoding="utf-8",
    )

    issues = lint_determinism._lint_file(target)

    assert issues == []


def test_lint_determinism_flags_direct_print_in_operational_modules(tmp_path: Path) -> None:
    target = tmp_path / "app" / "main.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def run():\n    print('status')\n", encoding="utf-8")

    issues = lint_determinism._lint_file(target)

    assert any(issue.message == "forbidden_direct_print" for issue in issues)


def test_lint_determinism_allows_direct_print_in_tools_cli_scripts(tmp_path: Path) -> None:
    target = tmp_path / "tools" / "cli.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def run():\n    print('user output')\n", encoding="utf-8")

    issues = lint_determinism._lint_file(target)

    assert all(issue.message != "forbidden_direct_print" for issue in issues)
