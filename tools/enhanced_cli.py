#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Enhanced CLI interface for ADAAD with rich terminal UI and real-time feedback."""

from __future__ import annotations

import argparse
import os
import selectors
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, Optional

from tools.error_dictionary import install_global_excepthook

ENV_MAX_SECONDS = "ADAAD_CLI_MAX_SECONDS"
ENV_IDLE_TIMEOUT_SECONDS = "ADAAD_CLI_IDLE_TIMEOUT_SECONDS"
ENV_TERMINATION_GRACE_SECONDS = "ADAAD_CLI_TERMINATION_GRACE_SECONDS"

EXIT_OK = 0
EXIT_CHILD_FAILURE = 1
EXIT_TIMEOUT_MAX_SECONDS = 124
EXIT_TIMEOUT_IDLE = 125
EXIT_FORCE_KILLED = 137


class TerminalUI:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    ICON_CHECK = "✓"
    ICON_CROSS = "✗"
    ICON_INFO = "ℹ"
    ICON_SHIELD = "🛡️"
    ICON_BRAIN = "🧠"
    ICON_DNA = "🧬"
    ICON_CLOCK = "⏱"

    @staticmethod
    def supports_color() -> bool:
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    @classmethod
    def color(cls, text: str, color: str, bold: bool = False) -> str:
        if not cls.supports_color():
            return text
        style = cls.BOLD if bold else ""
        return f"{style}{color}{text}{cls.RESET}"

    @classmethod
    def success(cls, text: str) -> str:
        return cls.color(f"{cls.ICON_CHECK} {text}", cls.GREEN, bold=True)

    @classmethod
    def error(cls, text: str) -> str:
        return cls.color(f"{cls.ICON_CROSS} {text}", cls.RED, bold=True)

    @classmethod
    def info(cls, text: str) -> str:
        return cls.color(f"{cls.ICON_INFO} {text}", cls.BLUE)

    @classmethod
    def header(cls, text: str) -> str:
        return cls.color(text, cls.CYAN, bold=True)

    @classmethod
    def dim(cls, text: str) -> str:
        if not cls.supports_color():
            return text
        return f"{cls.DIM}{text}{cls.RESET}"


@dataclass
class Stage:
    name: str
    description: str
    status: str = "pending"
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    def duration(self) -> Optional[float]:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None


@dataclass(frozen=True)
class ExitStatus:
    code: int
    reason: str
    timed_out: bool = False
    termination_sent: bool = False
    force_killed: bool = False


class EnhancedCLI:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.ui = TerminalUI()
        self.stages: Dict[str, Stage] = {}
        self.start_time = time.time()
        self.runtime_events: list[str] = []

    def print_banner(self) -> None:
        print()
        print(self.ui.header("╔═══════════════════════════════════════════════════════════╗"))
        print(self.ui.header("║         ADAAD - Autonomous Development System            ║"))
        print(self.ui.header("║    Deterministic, Policy-Governed Code Evolution         ║"))
        print(self.ui.header("╚═══════════════════════════════════════════════════════════╝"))
        print()

    def print_config_summary(self, config: dict) -> None:
        print(self.ui.header("Configuration:"))
        print(f"  {self.ui.ICON_SHIELD} Replay Mode: {config.get('replay_mode', 'off')}")
        print(f"  {self.ui.ICON_DNA} Mutation Enabled: {config.get('mutation_enabled', False)}")
        print(f"  {self.ui.ICON_BRAIN} Dry Run: {config.get('dry_run', False)}")
        print(f"  {self.ui.ICON_INFO} Verbose: {self.verbose}")
        if config.get("max_seconds") is not None:
            print(f"  {self.ui.ICON_CLOCK} Max Runtime: {config['max_seconds']}s")
        if config.get("idle_timeout_seconds") is not None:
            print(f"  {self.ui.ICON_CLOCK} Idle Timeout: {config['idle_timeout_seconds']}s")
        print()

    def start_stage(self, name: str, description: str) -> None:
        if name in self.stages:
            return
        stage = Stage(name=name, description=description, status="running", start_time=time.time())
        self.stages[name] = stage
        print(self.ui.info(f"[{len(self.stages)}] {description}..."))

    def complete_stage(self, name: str, success: bool, message: str = "") -> None:
        stage = self.stages.get(name)
        if not stage:
            return
        if stage.status in {"complete", "failed"}:
            return
        stage.end_time = time.time()
        stage.status = "complete" if success else "failed"
        duration = stage.duration()
        duration_str = f"({duration:.2f}s)" if duration else ""
        if success:
            print(self.ui.success(f"{stage.description} {duration_str}"))
        else:
            print(self.ui.error(f"{stage.description} {duration_str}"))
        if message:
            print(self.ui.dim(f"    └─ {message}"))

    def process_orchestrator_line(self, line: str) -> None:
        text = line.strip()
        lower = text.lower()
        print(text)
        if "gatekeeper" in lower:
            self.start_stage("gatekeeper", "Gatekeeper preflight checks")
            if "passed" in lower:
                self.complete_stage("gatekeeper", True, text)
        if "invariant" in lower:
            self.start_stage("invariants", "Runtime invariant verification")
            if "passed" in lower or "verified" in lower:
                self.complete_stage("invariants", True, text)
        if "cryovant" in lower:
            self.start_stage("cryovant", "Trust environment validation")
            if "passed" in lower or "valid" in lower:
                self.complete_stage("cryovant", True, text)
        if "replay decision" in lower or "replay mode" in lower:
            self.start_stage("replay", "Replay verification")
            self.complete_stage("replay", True, text)
        if "dashboard" in lower and "started" in lower:
            self.start_stage("dashboard", "Aponi dashboard startup")
            self.complete_stage("dashboard", True, text)

    def finalize_pending(self) -> None:
        for name in list(self.stages):
            stage = self.stages[name]
            if stage.status == "running":
                self.complete_stage(name, True, "completed")

    def print_final_summary(self, *, exit_status: Optional[ExitStatus] = None) -> None:
        total_duration = time.time() - self.start_time
        print()
        print(self.ui.header("═" * 60))
        print(self.ui.header("Execution Summary"))
        print(self.ui.header("═" * 60))
        completed = sum(1 for s in self.stages.values() if s.status == "complete")
        failed = sum(1 for s in self.stages.values() if s.status == "failed")
        print(f"  Total Stages: {len(self.stages)}")
        print(f"  {self.ui.success(f'Completed: {completed}')}")
        if failed:
            print(f"  {self.ui.error(f'Failed: {failed}')}")
        print(f"  {self.ui.ICON_CLOCK} Total Duration: {total_duration:.2f}s")
        if exit_status is not None:
            print(f"  Exit Mapping: {exit_status.code} ({exit_status.reason})")
        for event in self.runtime_events:
            print(self.ui.dim(f"  Event: {event}"))


def _env_float(name: str) -> Optional[float]:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number; got '{raw}'") from exc
    if value <= 0:
        raise ValueError(f"{name} must be > 0; got {value}")
    return value


def _read_orchestrator_output(
    process: subprocess.Popen[str],
    cli: EnhancedCLI,
    *,
    max_seconds: Optional[float],
    idle_timeout_seconds: Optional[float],
    termination_grace_seconds: float,
) -> ExitStatus:
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)

    started_at = time.monotonic()
    last_output_at = started_at

    while True:
        now = time.monotonic()
        if max_seconds is not None and now - started_at > max_seconds:
            reason = f"max runtime exceeded ({max_seconds:.2f}s)"
            return _terminate_process(
                process,
                cli,
                reason=reason,
                timed_out_code=EXIT_TIMEOUT_MAX_SECONDS,
                termination_grace_seconds=termination_grace_seconds,
            )
        if idle_timeout_seconds is not None and now - last_output_at > idle_timeout_seconds:
            reason = f"idle timeout exceeded ({idle_timeout_seconds:.2f}s since last output)"
            return _terminate_process(
                process,
                cli,
                reason=reason,
                timed_out_code=EXIT_TIMEOUT_IDLE,
                termination_grace_seconds=termination_grace_seconds,
            )

        ready = selector.select(timeout=0.05)
        if ready:
            line = process.stdout.readline()
            if line:
                last_output_at = time.monotonic()
                cli.process_orchestrator_line(line)
                continue

        rc = process.poll()
        if rc is not None:
            selector.unregister(process.stdout)
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                cli.process_orchestrator_line(line)
            reason = "ok" if rc == 0 else "child_failure"
            mapped = rc if rc != 0 else EXIT_OK
            if rc != 0:
                mapped = max(EXIT_CHILD_FAILURE, rc)
            return ExitStatus(code=mapped, reason=reason)


def _terminate_process(
    process: subprocess.Popen[str],
    cli: EnhancedCLI,
    *,
    reason: str,
    timed_out_code: int,
    termination_grace_seconds: float,
) -> ExitStatus:
    cli.runtime_events.append(f"timeout_detected: {reason}")
    process.terminate()
    cli.runtime_events.append(f"termination_sent: SIGTERM grace={termination_grace_seconds:.2f}s")

    try:
        process.wait(timeout=termination_grace_seconds)
        cli.runtime_events.append("process_terminated_gracefully")
        return ExitStatus(
            code=timed_out_code,
            reason=reason,
            timed_out=True,
            termination_sent=True,
            force_killed=False,
        )
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        cli.runtime_events.append("process_force_killed: SIGKILL")
        return ExitStatus(
            code=EXIT_FORCE_KILLED,
            reason=f"{reason}; force-killed after grace period",
            timed_out=True,
            termination_sent=True,
            force_killed=True,
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ADAAD enhanced CLI wrapper")
    parser.add_argument("--replay", choices=["off", "audit", "strict"], default="audit")
    parser.add_argument("--replay-epoch", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--dashboard", action="store_true")
    parser.add_argument("--verify-replay", action="store_true")
    parser.add_argument("--max-seconds", type=float, default=_env_float(ENV_MAX_SECONDS))
    parser.add_argument(
        "--idle-timeout-seconds",
        type=float,
        default=_env_float(ENV_IDLE_TIMEOUT_SECONDS),
    )
    parser.add_argument(
        "--termination-grace-seconds",
        type=float,
        default=_env_float(ENV_TERMINATION_GRACE_SECONDS) or 1.0,
        help=(
            "Seconds to wait after graceful terminate before force kill "
            f"(env: {ENV_TERMINATION_GRACE_SECONDS})."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    install_global_excepthook()

    parser = _build_parser()
    args = parser.parse_args(argv)

    cli = EnhancedCLI(verbose=args.verbose)
    cli.print_banner()
    config = {
        "replay_mode": args.replay,
        "replay_epoch": args.replay_epoch,
        "dry_run": args.dry_run,
        "mutation_enabled": not args.verify_replay,
        "dashboard": args.dashboard,
        "max_seconds": args.max_seconds,
        "idle_timeout_seconds": args.idle_timeout_seconds,
    }
    cli.print_config_summary(config)

    cmd = [sys.executable, "-m", "app.main", "--replay", args.replay]
    if args.replay_epoch:
        cmd.extend(["--replay-epoch", args.replay_epoch])
    if args.dry_run:
        cmd.append("--dry-run")
    if args.verbose:
        cmd.append("--verbose")
    if args.verify_replay:
        cmd.append("--verify-replay")

    cli.start_stage("orchestrator", "Launching ADAAD orchestrator")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    status = _read_orchestrator_output(
        process,
        cli,
        max_seconds=args.max_seconds,
        idle_timeout_seconds=args.idle_timeout_seconds,
        termination_grace_seconds=args.termination_grace_seconds,
    )

    cli.complete_stage("orchestrator", success=(status.code == EXIT_OK), message=f"exit_code={status.code} ({status.reason})")
    if status.code == EXIT_OK:
        cli.finalize_pending()
    cli.print_final_summary(exit_status=status)
    return int(status.code)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        raise SystemExit(1)
