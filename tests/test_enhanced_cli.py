# SPDX-License-Identifier: Apache-2.0

import subprocess
import sys

import pytest

from tools.enhanced_cli import (
    EXIT_FORCE_KILLED,
    EXIT_OK,
    EXIT_TIMEOUT_IDLE,
    EnhancedCLI,
    ExitStatus,
    _read_orchestrator_output,
)

pytestmark = pytest.mark.regression_standard


def _spawn_python(script: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def test_read_orchestrator_output_normal_completion_path() -> None:
    process = _spawn_python("print('gatekeeper passed')")
    cli = EnhancedCLI(verbose=False)

    status = _read_orchestrator_output(
        process,
        cli,
        max_seconds=2.0,
        idle_timeout_seconds=1.0,
        termination_grace_seconds=0.2,
    )

    assert status.code == EXIT_OK
    assert status.reason == "ok"
    assert cli.runtime_events == []


def test_read_orchestrator_output_idle_timeout_path() -> None:
    process = _spawn_python("import time; time.sleep(5)")
    cli = EnhancedCLI(verbose=False)

    status = _read_orchestrator_output(
        process,
        cli,
        max_seconds=2.0,
        idle_timeout_seconds=0.2,
        termination_grace_seconds=0.1,
    )

    assert status.code == EXIT_TIMEOUT_IDLE
    assert "idle timeout exceeded" in status.reason
    assert any("timeout_detected" in event for event in cli.runtime_events)
    assert any("termination_sent" in event for event in cli.runtime_events)


def test_read_orchestrator_output_forced_kill_path() -> None:
    process = _spawn_python(
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, lambda *_: None)\n"
        "time.sleep(5)"
    )
    cli = EnhancedCLI(verbose=False)

    status = _read_orchestrator_output(
        process,
        cli,
        max_seconds=2.0,
        idle_timeout_seconds=0.2,
        termination_grace_seconds=0.05,
    )

    assert status.code == EXIT_FORCE_KILLED
    assert status.force_killed is True
    assert any("process_force_killed" in event for event in cli.runtime_events)


def test_print_final_summary_renders_timeout_events(capsys) -> None:
    cli = EnhancedCLI(verbose=False)
    cli.start_stage("orchestrator", "Launching ADAAD orchestrator")
    cli.complete_stage("orchestrator", success=False, message="exit_code=125")
    cli.runtime_events.append("timeout_detected: idle timeout exceeded (0.20s since last output)")
    cli.runtime_events.append("termination_sent: SIGTERM grace=0.10s")

    cli.print_final_summary(
        exit_status=ExitStatus(
            code=EXIT_TIMEOUT_IDLE,
            reason="idle timeout exceeded (0.20s since last output)",
            timed_out=True,
            termination_sent=True,
        )
    )

    captured = capsys.readouterr().out
    assert "Exit Mapping: 125" in captured
    assert "idle timeout exceeded" in captured
    assert "Event: timeout_detected" in captured
