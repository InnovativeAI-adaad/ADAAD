#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Enhanced CLI interface for ADAAD with rich terminal UI and real-time feedback."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from tools.error_dictionary import install_global_excepthook


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


class EnhancedCLI:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.ui = TerminalUI()
        self.stages: Dict[str, Stage] = {}
        self.start_time = time.time()

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

    def print_final_summary(self) -> None:
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


def main(argv: list[str] | None = None) -> int:
    install_global_excepthook()

    parser = argparse.ArgumentParser(description="ADAAD enhanced CLI wrapper")
    parser.add_argument("--replay", choices=["off", "audit", "strict"], default="audit")
    parser.add_argument("--replay-epoch", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--dashboard", action="store_true")
    parser.add_argument("--verify-replay", action="store_true")
    args = parser.parse_args(argv)

    cli = EnhancedCLI(verbose=args.verbose)
    cli.print_banner()
    config = {
        "replay_mode": args.replay,
        "replay_epoch": args.replay_epoch,
        "dry_run": args.dry_run,
        "mutation_enabled": not args.verify_replay,
        "dashboard": args.dashboard,
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
    assert process.stdout is not None
    for line in process.stdout:
        cli.process_orchestrator_line(line)
    rc = process.wait()

    cli.complete_stage("orchestrator", success=(rc == 0), message=f"exit_code={rc}")
    if rc == 0:
        cli.finalize_pending()
    cli.print_final_summary()
    return int(rc)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        raise SystemExit(1)
