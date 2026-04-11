# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_default_pytest_discovery_excludes_archives_tests() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--collect-only",
        "--continue-on-collection-errors",
        "-q",
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        cwd=repo_root,
        text=True,
        check=False,
    )

    collected_output = f"{completed.stdout}\n{completed.stderr}"

    assert "archives/tests" not in collected_output
