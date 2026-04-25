# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
import ast

import pytest
pytestmark = pytest.mark.regression_standard

from tools import lint_determinism


# Current-policy contract tests (must pass now)

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


def test_lint_determinism_flags_importlib_alias_usage_in_orchestrator_scope(tmp_path: Path) -> None:
    target = tmp_path / "adaad" / "orchestrator" / "dispatch_bad_alias.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("import importlib as il\n\ndef route():\n    return il.import_module('json')\n", encoding="utf-8")

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


def test_lint_determinism_flags_entropy_calls_in_orchestrator_scope(tmp_path: Path) -> None:
    target = tmp_path / "adaad" / "orchestrator" / "dispatch_entropy.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("import time\n\ndef route():\n    return time.time()\n", encoding="utf-8")

    issues = lint_determinism._lint_file(target)

    assert issues
    assert any(issue.message == "forbidden_entropy_source" for issue in issues)


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
import ast


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


def test_lint_determinism_allows_direct_print_in_tools_cli_scripts(tmp_path: Path) -> None:
    target = tmp_path / "tools" / "cli.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def run():\n    print('user output')\n", encoding="utf-8")

    issues = lint_determinism._lint_file(target)

    assert all(issue.message != "forbidden_direct_print" for issue in issues)


def test_lint_determinism_flags_direct_nondeterministic_calls_in_governance_critical_scope(tmp_path: Path) -> None:
    target = tmp_path / "security" / "entropy.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("import uuid\n\ndef run():\n    return uuid.uuid4().hex\n", encoding="utf-8")

    issues = lint_determinism._lint_file(target)

    assert any(issue.message == "forbidden_governance_nondeterminism_api" for issue in issues)


def test_lint_determinism_allows_approved_wrapper_for_nondeterminism_calls(tmp_path: Path) -> None:
    target = tmp_path / "runtime" / "governance" / "provider.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "import uuid\n\ndef next_id():\n    return uuid.uuid4().hex\n",
        encoding="utf-8",
    )

    issues = lint_determinism._lint_file(target)

    assert all(issue.message != "forbidden_governance_nondeterminism_api" for issue in issues)


def test_lint_required_governance_files_include_runtime_evolution_and_federation_modules() -> None:
    required = set(lint_determinism.REQUIRED_GOVERNANCE_FILES)
    assert "runtime/evolution/fitness_orchestrator.py" in required
    assert "runtime/evolution/economic_fitness.py" in required
    assert "runtime/governance/federation/protocol.py" in required
    assert "runtime/governance/federation/manifest.py" in required
    assert "runtime/fitness/orchestrator.py" not in required


def test_lint_determinism_flags_entropy_calls_in_replay_sensitive_app_scope(tmp_path: Path) -> None:
    target = tmp_path / "app" / "dream_mode.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "import time\n\ndef run():\n    return time.time()\n",
        encoding="utf-8",
    )

    issues = lint_determinism._lint_file(target)

    assert issues
    assert any(issue.message == "forbidden_entropy_source" for issue in issues)


def test_lint_determinism_allows_documented_entropy_exception_for_beast_mode(tmp_path: Path) -> None:
    target = tmp_path / "app" / "beast_mode_loop.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "import time\n\ndef _clock():\n    return time.time(), time.monotonic()\n",
        encoding="utf-8",
    )

    issues = lint_determinism._lint_file(target)

    assert all(issue.message != "forbidden_entropy_source" for issue in issues)


def test_lint_determinism_flags_direct_print_in_operational_modules(tmp_path: Path) -> None:
    target = tmp_path / "app" / "main.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def run():\n    print('status')\n", encoding="utf-8")

    issues = lint_determinism._lint_file(target)

    assert any(issue.message == "forbidden_direct_print" for issue in issues)


def _call_path(node):

    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        return _call_path(node.value) + (node.attr,)
    return ()


def test_dream_mode_hardened_path_forbids_wall_clock_sources_but_allows_wrappers() -> None:
    source = Path("app/dream_mode.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    dream_mode = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "DreamMode")
    run_cycle = next(node for node in dream_mode.body if isinstance(node, ast.FunctionDef) and node.name == "run_cycle")

    forbidden_paths = {
        ("time", "time"),
        ("time", "strftime"),
        ("time", "gmtime"),
    }
    approved_wrapper_paths = {
        ("self", "provider", "next_token"),
        ("self", "provider", "iso_now"),
        ("deterministic_token_with_budget",),
    }

    run_cycle_calls = {_call_path(node.func) for node in ast.walk(run_cycle) if isinstance(node, ast.Call)}
    assert forbidden_paths.isdisjoint(run_cycle_calls)
    assert approved_wrapper_paths.intersection(run_cycle_calls)
