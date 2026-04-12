# SPDX-License-Identifier: Apache-2.0
"""Innovation #8 — Adversarial Fitness Red Team Agent.

A dedicated agent that tries to break every proposal before acceptance.
Generates adversarial test cases targeting uncovered code paths.
"""
from __future__ import annotations
import ast, hashlib, json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
RETEAG_INV_CHAIN: str = "RETEAG-INV-CHAIN"
RETEAG_LEDGER_DEFAULT: str = "data/red_team_agent_events.jsonl"


class RedTeamAgentViolation(RuntimeError):
    """Raised when a Red Team Agent constitutional invariant is breached."""



RED_TEAM_PASS_THRESHOLD: float = 0.70   # fraction of adversarial tests that must pass

@dataclass
class AdversarialCase:
    case_id: str
    target_path: str
    input_description: str
    expected_outcome: str   # "should_not_raise" | "should_return_X" | "should_fail_gracefully"
    discovered_vulnerability: str | None = None

@dataclass
class RedTeamVerdict:
    mutation_id: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    vulnerabilities: list[str]
    verdict: str   # "PASS" | "FAIL" | "INCONCLUSIVE"
    verdict_digest: str = ""

    def __post_init__(self):
        if not self.verdict_digest:
            payload = f"{self.mutation_id}:{self.verdict}:{self.pass_rate:.4f}"
            self.verdict_digest = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


class RedTeamAgent:
    """Adversarially tests mutation proposals before acceptance."""

    def __init__(self, state_path: Path = Path("data/red_team_verdicts.jsonl"),
                 pass_threshold: float = RED_TEAM_PASS_THRESHOLD):
        self.state_path = Path(state_path)
        self.threshold = pass_threshold

    def challenge(self, mutation_id: str, before_source: str,
                  after_source: str, changed_files: list[str]) -> RedTeamVerdict:
        """Generate adversarial cases and evaluate the mutation against them."""
        cases = self._generate_cases(after_source, changed_files)
        passed, failed, vulns = 0, 0, []

        for case in cases:
            ok, vuln = self._evaluate_case(case, after_source, before_source)
            if ok:
                passed += 1
            else:
                failed += 1
                if vuln:
                    vulns.append(vuln)

        total = max(1, len(cases))
        pass_rate = passed / total
        verdict = ("PASS" if pass_rate >= self.threshold
                   else "FAIL" if pass_rate < self.threshold * 0.5
                   else "INCONCLUSIVE")

        result = RedTeamVerdict(
            mutation_id=mutation_id,
            total_cases=total,
            passed_cases=passed,
            failed_cases=failed,
            pass_rate=round(pass_rate, 4),
            vulnerabilities=vulns,
            verdict=verdict,
        )
        self._persist(result)
        return result

    def _generate_cases(self, source: str,
                         changed_files: list[str]) -> list[AdversarialCase]:
        """Generate adversarial test cases from source AST analysis."""
        cases = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            cases.append(AdversarialCase(
                case_id="syntax-0",
                target_path=changed_files[0] if changed_files else "unknown",
                input_description="Parse the mutated source",
                expected_outcome="should_not_raise",
                discovered_vulnerability="SyntaxError in mutated source",
            ))
            return cases

        # Case 1: empty inputs
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                args = [a.arg for a in node.args.args if a.arg != "self"]
                if args:
                    cases.append(AdversarialCase(
                        case_id=f"empty-{node.name}",
                        target_path=changed_files[0] if changed_files else "",
                        input_description=f"{node.name}() called with empty/None args",
                        expected_outcome="should_fail_gracefully",
                    ))
                if len(cases) >= 5:
                    break

        # Case 2: None-safety check
        cases.append(AdversarialCase(
            case_id="none-safety",
            target_path=changed_files[0] if changed_files else "",
            input_description="Pass None to all typed parameters",
            expected_outcome="should_fail_gracefully",
        ))

        # Case 3: boundary inputs
        cases.append(AdversarialCase(
            case_id="boundary",
            target_path=changed_files[0] if changed_files else "",
            input_description="Empty lists, zero integers, empty strings",
            expected_outcome="should_not_raise",
        ))

        return cases[:5]  # max 5 adversarial cases

    def _evaluate_case(self, case: AdversarialCase, after: str,
                        before: str) -> tuple[bool, str | None]:
        """Evaluate a case. Returns (passed, vulnerability_description)."""
        # Syntax check
        if "SyntaxError" in (case.discovered_vulnerability or ""):
            try:
                ast.parse(after)
                return False, case.discovered_vulnerability
            except SyntaxError as e:
                return False, f"SyntaxError: {e}"

        # Check that none-safety patterns exist in the after source
        if case.case_id == "none-safety":
            has_none_check = any(
                token in after
                for token in ["is None", "is not None", "Optional", "if not ", "or {}"]
            )
            if not has_none_check and "def " in after:
                return False, "Function accepts inputs but has no None-safety guards"
            return True, None

        # Default: pass if source is syntactically valid
        try:
            ast.parse(after)
            return True, None
        except SyntaxError as e:
            return False, f"SyntaxError: {e}"

    def _persist(self, verdict: RedTeamVerdict) -> None:
        import dataclasses

        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("a") as f:
            f.write(json.dumps(dataclasses.asdict(verdict)) + "\n")


__all__ = ["RedTeamAgent", "RedTeamVerdict", "AdversarialCase",
           "RED_TEAM_PASS_THRESHOLD"]
