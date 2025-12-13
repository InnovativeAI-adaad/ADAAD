from __future__ import annotations

import shlex
import subprocess
from typing import List

from tools.codex.contracts import TestResult


def run_command(command: str) -> TestResult:
    process = subprocess.run(
        command if isinstance(command, list) else shlex.split(command),
        capture_output=True,
        text=True,
        check=False,
    )
    return TestResult(
        command=command,
        returncode=process.returncode,
        stdout=process.stdout,
        stderr=process.stderr,
    )


def run_commands(commands: List[str]) -> List[TestResult]:
    return [run_command(command) for command in commands]
