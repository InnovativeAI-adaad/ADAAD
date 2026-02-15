#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Enhanced error handling and user-friendly diagnostic messages for ADAAD."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Dict, List, Optional


class ErrorCategory(Enum):
    """Categories of errors users might encounter."""

    SETUP = "setup"
    CONFIGURATION = "configuration"
    GOVERNANCE = "governance"
    REPLAY = "replay"
    MUTATION = "mutation"
    SYSTEM = "system"
    NETWORK = "network"


@dataclass(frozen=True)
class DiagnosticSolution:
    """A potential solution to an error."""

    description: str
    command: Optional[str] = None
    explanation: str = ""


@dataclass(frozen=True)
class EnhancedError:
    """Enhanced error with context and solutions."""

    code: str
    title: str
    message: str
    category: ErrorCategory
    solutions: List[DiagnosticSolution]
    learn_more_url: Optional[str] = None

    def format_for_user(self, verbose: bool = False) -> str:
        output = []
        output.append("╔═══════════════════════════════════════════════════════════╗")
        output.append(f"║  ⚠️  {self.title[:55].center(55)} ║")
        output.append("╚═══════════════════════════════════════════════════════════╝")
        output.append("")
        output.append("📋 What happened:")
        output.append(f"   {self.message}")
        output.append("")
        output.append(f"🏷️  Category: {self.category.value}")
        output.append(f"🔍 Error Code: {self.code}")
        output.append("")

        if self.solutions:
            output.append("💡 How to fix this:")
            for i, solution in enumerate(self.solutions, 1):
                output.append(f"\n   Option {i}: {solution.description}")
                if solution.command:
                    output.append("   Run this command:")
                    output.append(f"   $ {solution.command}")
                if solution.explanation and verbose:
                    output.append(f"   ℹ️  {solution.explanation}")

        if self.learn_more_url:
            output.append("")
            output.append(f"📚 Learn more: {self.learn_more_url}")

        output.append("")
        output.append("─" * 63)
        return "\n".join(output)


class ErrorDictionary:
    """Comprehensive dictionary of ADAAD errors with solutions."""

    ERRORS: Dict[str, EnhancedError] = {
        "E001": EnhancedError(
            code="E001",
            title="Missing Dependencies",
            message="Required Python packages are not installed or not accessible.",
            category=ErrorCategory.SETUP,
            solutions=[
                DiagnosticSolution(
                    description="Reinstall dependencies in your virtual environment",
                    command="pip install -r requirements.server.txt",
                    explanation="This ensures all required packages are properly installed.",
                ),
                DiagnosticSolution(
                    description="Verify your virtual environment is activated",
                    command="source .venv/bin/activate  # macOS/Linux | .venv\\Scripts\\activate  # Windows",
                    explanation="ADAAD should run inside a Python virtual environment.",
                ),
            ],
            learn_more_url="https://github.com/InnovativeAI-adaad/ADAAD/blob/main/QUICKSTART.md",
        ),
        "E002": EnhancedError(
            code="E002",
            title="Workspace Not Initialized",
            message="ADAAD workspace has not been set up. Required directories and files are missing.",
            category=ErrorCategory.SETUP,
            solutions=[
                DiagnosticSolution(
                    description="Initialize the ADAAD workspace",
                    command="python nexus_setup.py",
                    explanation="Creates required directories and initializes base runtime state.",
                )
            ],
        ),
        "E101": EnhancedError(
            code="E101",
            title="Invalid Replay Mode",
            message="Replay mode must be one of 'off', 'audit', or 'strict'.",
            category=ErrorCategory.CONFIGURATION,
            solutions=[
                DiagnosticSolution(
                    description="Use a valid replay mode",
                    command="python -m app.main --replay audit --verbose",
                    explanation="Use audit for development; strict for high-assurance verification.",
                )
            ],
        ),
        "E201": EnhancedError(
            code="E201",
            title="Constitution Policy Rejection",
            message="A mutation was rejected by constitutional policy checks.",
            category=ErrorCategory.GOVERNANCE,
            solutions=[
                DiagnosticSolution(
                    description="Review mutation tier and constitution rules",
                    explanation="Higher-risk changes require explicit policy elevation.",
                ),
                DiagnosticSolution(
                    description="Run dry-run to inspect rejection details",
                    command="python -m app.main --dry-run --verbose",
                ),
            ],
            learn_more_url="https://github.com/InnovativeAI-adaad/ADAAD/blob/main/docs/CONSTITUTION.md",
        ),
        "E301": EnhancedError(
            code="E301",
            title="Replay Baseline Mismatch",
            message="Current state does not match the expected replay baseline.",
            category=ErrorCategory.REPLAY,
            solutions=[
                DiagnosticSolution(
                    description="Run in audit mode to inspect divergence",
                    command="python -m app.main --replay audit --verbose",
                    explanation="Audit mode provides divergence signal without strict halt semantics.",
                ),
                DiagnosticSolution(
                    description="Inspect replay forensics endpoints",
                    command="curl http://localhost:8080/replay/divergence && curl 'http://localhost:8080/replay/diff?epoch_id=<id>'",
                ),
            ],
        ),
        "E401": EnhancedError(
            code="E401",
            title="Mutation Rate Limit Exceeded",
            message="Maximum allowed mutation rate was exceeded.",
            category=ErrorCategory.MUTATION,
            solutions=[
                DiagnosticSolution(
                    description="Wait for the rate window to reset",
                    explanation="Rate limiting is a safety control to reduce mutation pressure.",
                ),
                DiagnosticSolution(
                    description="Adjust rate limit conservatively",
                    command="export ADAAD_MAX_MUTATIONS_PER_HOUR=120",
                ),
            ],
        ),
        "E502": EnhancedError(
            code="E502",
            title="Ledger Journal Corruption",
            message="The append-only ledger journal failed integrity checks.",
            category=ErrorCategory.SYSTEM,
            solutions=[
                DiagnosticSolution(
                    description="Verify ledger integrity",
                    command="python -c \"from security.ledger import journal; print(journal.verify_integrity())\"",
                ),
                DiagnosticSolution(
                    description="Restore from known-good ledger snapshot",
                    explanation="Use approved recovery runbook steps before resuming mutation cycles.",
                ),
            ],
        ),
        "E601": EnhancedError(
            code="E601",
            title="Dashboard Port Already in Use",
            message="Cannot start dashboard because configured port is occupied.",
            category=ErrorCategory.NETWORK,
            solutions=[
                DiagnosticSolution(
                    description="Use a different dashboard port",
                    command="export APONI_PORT=8081 && python -m app.main --verbose",
                ),
                DiagnosticSolution(
                    description="Stop conflicting process",
                    command="lsof -ti:8080 | xargs kill -9  # macOS/Linux",
                ),
            ],
        ),
    }

    @classmethod
    def get_error(cls, code: str) -> Optional[EnhancedError]:
        return cls.ERRORS.get(code)

    @classmethod
    def suggest_error(cls, exception_or_message: object) -> Optional[EnhancedError]:
        error_msg = str(exception_or_message).lower()
        type_name = str(type(exception_or_message)).lower()

        if "no module named" in error_msg or "importerror" in type_name:
            return cls.get_error("E001")
        if "permission" in error_msg or "access denied" in error_msg:
            return cls.get_error("E502")
        if "replay" in error_msg and ("mismatch" in error_msg or "baseline" in error_msg):
            return cls.get_error("E301")
        if "rate limit" in error_msg:
            return cls.get_error("E401")
        if "constitution" in error_msg:
            return cls.get_error("E201")
        if "port" in error_msg and "use" in error_msg:
            return cls.get_error("E601")
        return None

    @classmethod
    def print_error(cls, error: EnhancedError, verbose: bool = False) -> None:
        print()
        print(error.format_for_user(verbose=verbose))
        print()


    @classmethod
    def handle_exception(cls, exc_type, exc, _tb) -> None:
        suggested = cls.suggest_error(exc)
        if suggested:
            cls.print_error(suggested, verbose=True)
        else:
            print(f"Unhandled exception: {exc}")


def install_global_excepthook() -> None:
    """Install ADAAD-friendly exception hook for user-facing tools."""

    import sys

    sys.excepthook = ErrorDictionary.handle_exception


def handle_adaad_error(func):
    """Decorator to catch and display ADAAD errors with useful diagnostics."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            suggested = ErrorDictionary.suggest_error(exc)
            if suggested:
                ErrorDictionary.print_error(suggested, verbose=True)
            else:
                print("\n╔═══════════════════════════════════════════════════════════╗")
                print("║  ⚠️  An unexpected error occurred                        ║")
                print("╚═══════════════════════════════════════════════════════════╝\n")
                print(f"Error: {exc}\n")
                print("💡 Tips:")
                print("   • Run with --verbose for more details")
                print("   • Check reports/metrics.jsonl for logs")
                print("   • Visit https://github.com/InnovativeAI-adaad/ADAAD/issues\n")
            raise

    return wrapper


def main() -> int:
    print("ADAAD Error Dictionary - All Error Messages\n")
    print("=" * 70)
    for code in sorted(ErrorDictionary.ERRORS):
        print(f"\n{ErrorDictionary.ERRORS[code].format_for_user(verbose=True)}")
        print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
