#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Interactive onboarding guide for first-time ADAAD users."""

from __future__ import annotations

import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, List, Tuple


class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    END = "\033[0m"


class OnboardingGuide:
    def __init__(self) -> None:
        self.total_steps = 8
        self.checks_passed: List[str] = []
        self.checks_failed: List[str] = []

    @staticmethod
    def _c(text: str, color: str) -> str:
        return f"{color}{text}{Colors.END}" if sys.stdout.isatty() else text

    def print_header(self) -> None:
        print(f"\n{self._c('=' * 70, Colors.CYAN)}")
        print(self._c("    🎓 Welcome to ADAAD - Interactive Onboarding Guide", Colors.HEADER + Colors.BOLD))
        print(f"{self._c('=' * 70, Colors.CYAN)}\n")
        print(self._c("This guide walks through setup with validation at each step.", Colors.BLUE))

    def print_step_header(self, step_num: int, title: str) -> None:
        print(f"\n{self._c(f'[Step {step_num}/{self.total_steps}] {title}', Colors.BOLD + Colors.CYAN)}")
        print(self._c("─" * 70, Colors.CYAN))

    def run_check(self, name: str, check_func: Callable[[], Tuple[bool, str]]) -> bool:
        print(self._c(f"Checking: {name}...", Colors.CYAN), end=" ")
        sys.stdout.flush()
        try:
            ok, detail = check_func()
            if ok:
                print(self._c("✓", Colors.GREEN))
                self.checks_passed.append(name)
                if detail:
                    print(self._c(f"  {detail}", Colors.BLUE))
                return True
            print(self._c("✗", Colors.RED))
            self.checks_failed.append(name)
            if detail:
                print(self._c(f"  {detail}", Colors.RED))
            return False
        except Exception as exc:
            print(self._c("✗", Colors.RED))
            self.checks_failed.append(name)
            print(self._c(f"  Error: {exc}", Colors.RED))
            return False

    @staticmethod
    def wait_for_user(prompt: str = "Press Enter to continue...") -> None:
        input(prompt)

    @staticmethod
    def check_python_version() -> Tuple[bool, str]:
        v = sys.version_info
        if (v.major, v.minor) >= (3, 10):
            return True, f"Python {v.major}.{v.minor}.{v.micro}"
        return False, f"Python 3.10+ required, found {v.major}.{v.minor}.{v.micro}"

    @staticmethod
    def check_git() -> Tuple[bool, str]:
        try:
            result = subprocess.run(["git", "--version"], capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return False, "Git not installed"
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, "Git not found"

    @staticmethod
    def check_directory() -> Tuple[bool, str]:
        if Path("README.md").exists() and Path("app").exists():
            return True, "In ADAAD repository directory"
        return False, "Not in ADAAD directory"

    @staticmethod
    def check_venv() -> Tuple[bool, str]:
        in_venv = hasattr(sys, "real_prefix") or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix)
        return (True, "Virtual environment active") if in_venv else (False, "Virtual environment not active")

    @staticmethod
    def check_dependencies() -> Tuple[bool, str]:
        try:
            import runtime  # noqa: F401
            import security  # noqa: F401
        except ImportError as exc:
            return False, f"Missing dependencies: {exc}"
        return True, "Core dependencies import successfully"

    @staticmethod
    def check_workspace() -> Tuple[bool, str]:
        required = ["reports", "security/ledger", "data"]
        missing = [d for d in required if not Path(d).exists()]
        if missing:
            return False, f"Missing directories: {', '.join(missing)}"
        return True, "Workspace initialized"

    @staticmethod
    def check_port_8080_available() -> Tuple[bool, str]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", 8080))
            return True, "Port 8080 available"
        except OSError:
            return False, "Port 8080 already in use"
        finally:
            sock.close()

    @staticmethod
    def check_disk_space() -> Tuple[bool, str]:
        usage = shutil.disk_usage(Path.cwd())
        free_mb = usage.free // (1024 * 1024)
        if free_mb >= 512:
            return True, f"Free disk space: {free_mb} MB"
        return False, f"Insufficient free disk space: {free_mb} MB (need >= 512 MB)"

    @staticmethod
    def check_git_integrity() -> Tuple[bool, str]:
        if not Path('.git').exists():
            return False, "Not a git repository"
        result = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip() == "true":
            return True, "Git repository integrity OK"
        return False, "Git repository integrity check failed"

    @staticmethod
    def check_minimum_package_versions() -> Tuple[bool, str]:
        # Conservative import check for critical modules without network/package mutation.
        try:
            import jsonschema  # type: ignore # optional runtime dependency in this repo setup
            _ = getattr(jsonschema, "__version__", "unknown")
        except Exception:
            return False, "jsonschema unavailable; install requirements.server.txt"
        return True, "Critical package imports validated"

    def step_1_prereq(self) -> bool:
        self.print_step_header(1, "Checking prerequisites")
        ok = True
        ok &= self.run_check("Python 3.10+", self.check_python_version)
        ok &= self.run_check("Git", self.check_git)
        ok &= self.run_check("Port 8080 availability", self.check_port_8080_available)
        ok &= self.run_check("Disk space", self.check_disk_space)
        ok &= self.run_check("Git integrity", self.check_git_integrity)
        return ok

    def step_2_repo(self) -> bool:
        self.print_step_header(2, "Repository setup")
        if self.run_check("ADAAD directory", self.check_directory):
            return True
        print(self._c("Run: git clone https://github.com/InnovativeAI-adaad/ADAAD.git", Colors.BLUE))
        print(self._c("Then: cd ADAAD", Colors.BLUE))
        self.wait_for_user()
        return self.run_check("ADAAD directory", self.check_directory)

    def step_3_venv(self) -> bool:
        self.print_step_header(3, "Virtual environment")
        if self.run_check("Virtual environment", self.check_venv):
            return True
        print(self._c("Run: python -m venv .venv", Colors.BLUE))
        if platform.system().lower().startswith("win"):
            print(self._c("Run: .venv\\Scripts\\Activate.ps1", Colors.BLUE))
        else:
            print(self._c("Run: source .venv/bin/activate", Colors.BLUE))
        self.wait_for_user()
        return self.run_check("Virtual environment", self.check_venv)

    def step_4_deps(self) -> bool:
        self.print_step_header(4, "Install dependencies")
        if self.run_check("Dependencies installed", self.check_dependencies) and self.run_check("Minimum package versions", self.check_minimum_package_versions):
            return True
        print(self._c("Run: pip install -r requirements.server.txt", Colors.BLUE))
        self.wait_for_user()
        deps_ok = self.run_check("Dependencies installed", self.check_dependencies)
        pkg_ok = self.run_check("Minimum package versions", self.check_minimum_package_versions)
        return deps_ok and pkg_ok

    def step_5_workspace(self) -> bool:
        self.print_step_header(5, "Initialize workspace")
        if self.run_check("Workspace initialized", self.check_workspace):
            return True
        print(self._c("Run: python nexus_setup.py", Colors.BLUE))
        self.wait_for_user()
        return self.run_check("Workspace initialized", self.check_workspace)

    def step_6_first_run(self) -> bool:
        self.print_step_header(6, "First ADAAD run")
        print(self._c("Run: python -m app.main --replay audit --verbose", Colors.BLUE))
        self.wait_for_user("After running the command, press Enter...")
        return True

    def step_7_dashboard(self) -> bool:
        self.print_step_header(7, "Dashboard exploration")
        print(self._c("Open: http://localhost:8080", Colors.BLUE))
        print(self._c("Useful endpoints: /state /metrics /lineage /mutations", Colors.BLUE))
        self.wait_for_user()
        return True

    def step_8_next(self) -> bool:
        self.print_step_header(8, "Next steps")
        print(self._c("Try: python -m app.main --dry-run --verbose", Colors.BLUE))
        print(self._c("Try: python -m app.main --verify-replay --replay audit --verbose", Colors.BLUE))
        print(self._c("Docs: README.md QUICKSTART.md docs/manifest.txt", Colors.BLUE))
        return True

    def print_summary(self) -> None:
        total = len(self.checks_passed) + len(self.checks_failed)
        print(f"\n{self._c('=' * 70, Colors.CYAN)}")
        print(self._c("    📊 Onboarding Summary", Colors.HEADER + Colors.BOLD))
        print(self._c(f"Passed: {len(self.checks_passed)}/{total}", Colors.GREEN))
        if self.checks_failed:
            print(self._c(f"Failed: {len(self.checks_failed)}/{total}", Colors.RED))

    def run(self) -> int:
        self.print_header()
        steps = [
            self.step_1_prereq,
            self.step_2_repo,
            self.step_3_venv,
            self.step_4_deps,
            self.step_5_workspace,
            self.step_6_first_run,
            self.step_7_dashboard,
            self.step_8_next,
        ]
        for step in steps:
            if not step():
                retry = input(self._c("Step failed. Retry? (y/n): ", Colors.YELLOW)).strip().lower()
                if retry != "y" or not step():
                    break
            time.sleep(0.2)
        self.print_summary()
        return 0 if not self.checks_failed else 1


def main() -> int:
    try:
        return OnboardingGuide().run()
    except KeyboardInterrupt:
        print("\nOnboarding interrupted.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
