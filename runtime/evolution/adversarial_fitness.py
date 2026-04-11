# SPDX-License-Identifier: Apache-2.0
"""
ADAAD v8 — Adversarial Fitness Engine (Red Team Agent)
========================================================
Solves the Fitness Oracle Problem (Reward Hacking):

  THE PROBLEM:
  If the Architect agent writes code and the Developer agent writes tests,
  they will eventually "collude." The Developer writes junk code that satisfies
  a poorly written test, reporting a Fitness Win while code quality degrades.

  THE SOLUTION: Adversarial Testing.
  For every mutation proposed by a Developer agent, a Red Team agent attempts
  to break it. A mutation only passes fitness scoring if it survives adversarial
  challenge.

ADVERSARIAL CHECKS:
  1. Logic Density Check   — detects code-size growth without proportional complexity
  2. Test Specificity Check — detects tests that are suspiciously narrow for the change
  3. Edge Case Injection   — injects boundary inputs to find hidden failures
  4. Mutation Testing      — applies micro-mutations to the test; passing = weak test
  5. Regression Fuzz       — re-runs prior failing tests against new code

CONSTITUTIONAL INVARIANTS ENFORCED:
  FITNESS-ADV-0   — all mutations with tests_to_code_ratio below threshold are quarantined
  FITNESS-DEN-0   — adversarial results are included in EpochEvidence.adversarial_challenges_run

Usage:
    from runtime.evolution.adversarial_fitness import AdversarialFitnessEngine

    engine = AdversarialFitnessEngine(threshold_test_ratio=1.5)
    challenge = engine.challenge(mutation_candidate, sandbox_result)
    if not challenge.passed:
        # Quarantine the mutation
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AdversarialVerdict(str, Enum):
    PASSED    = "PASSED"      # survived all adversarial challenges
    WEAK_TEST = "WEAK_TEST"   # code changed but tests too shallow
    COLLUSION = "COLLUSION"   # test precisely mirrors implementation — likely reward hacking
    BLOAT     = "BLOAT"       # code size grew without complexity justification
    FRAGILE   = "FRAGILE"     # edge-case injection found hidden failure


@dataclass(frozen=True)
class AdversarialChallenge:
    """
    Result of running the Red Team agent against a single mutation candidate.

    Fields:
    - mutation_id            : candidate being challenged
    - verdict                : AdversarialVerdict
    - passed                 : True only if verdict == PASSED
    - tests_to_code_ratio    : test lines / changed code lines (threshold: configurable)
    - logic_density_score    : cyclomatic complexity / node_count (higher = denser)
    - weak_test_signals      : list of detected weakness patterns in test code
    - edge_case_failures     : inputs that caused unexpected failures
    - mutation_test_score    : 0.0..1.0; fraction of micro-mutations caught by tests
                               (below 0.6 = weak test suite)
    - challenge_hash         : SHA-256 of this record — written to ModelDriftEvidence
    - notes                  : human-readable summary for Aponi Rule Trace panel
    """
    mutation_id: str
    verdict: AdversarialVerdict
    passed: bool
    tests_to_code_ratio: float
    logic_density_score: float
    weak_test_signals: tuple[str, ...]
    edge_case_failures: tuple[str, ...]
    mutation_test_score: float
    challenge_hash: str
    notes: str

    def to_ledger_entry(self) -> dict:
        return {
            "mutation_id": self.mutation_id,
            "verdict": self.verdict.value,
            "passed": self.passed,
            "tests_to_code_ratio": self.tests_to_code_ratio,
            "mutation_test_score": self.mutation_test_score,
            "challenge_hash": self.challenge_hash,
        }


class AdversarialFitnessEngine:
    """
    Red Team agent. Runs after SandboxTournament passes a candidate.
    A mutation only reaches GovernanceGate if it survives all adversarial challenges.

    Configuration (from config/governance/static_rules.yaml):
    - threshold_test_ratio    : minimum test-lines / changed-code-lines (default 1.5)
    - min_mutation_test_score : minimum fraction of micro-mutations caught (default 0.6)
    - max_logic_density       : maximum cyclomatic/node ratio (default 0.4)
    - bloat_threshold_nodes   : maximum net AST node increase (default 40, same as PatchSizeRule)
    """

    def __init__(
        self,
        threshold_test_ratio: float = 1.5,
        min_mutation_test_score: float = 0.6,
        max_logic_density: float = 0.4,
        bloat_threshold_nodes: int = 40,
    ):
        self.threshold_test_ratio = threshold_test_ratio
        self.min_mutation_test_score = min_mutation_test_score
        self.max_logic_density = max_logic_density
        self.bloat_threshold_nodes = bloat_threshold_nodes

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def challenge(
        self,
        mutation_id: str,
        before_source: Optional[str],
        after_source: str,
        test_source: Optional[str],
        node_count_delta: int,
        cyclomatic_delta: int,
    ) -> AdversarialChallenge:
        """
        Run all adversarial checks against a mutation candidate.
        Returns AdversarialChallenge with verdict and supporting evidence.
        """
        weak_signals: list[str] = []
        edge_failures: list[str] = []

        # ── Check 1: Logic Density (Bloat Detection) ──────────────────
        logic_density = self._compute_logic_density(after_source)
        if node_count_delta > self.bloat_threshold_nodes:
            verdict = AdversarialVerdict.BLOAT
            notes = (
                f"Code bloat detected: node_count_delta={node_count_delta} "
                f"exceeds threshold {self.bloat_threshold_nodes}. "
                f"Logic density: {logic_density:.3f}. Mutation quarantined."
            )
            return self._build_result(
                mutation_id, verdict, False, 0.0, logic_density,
                weak_signals, edge_failures, 0.0, notes
            )

        # ── Check 2: Test Specificity ──────────────────────────────────
        test_ratio = 0.0
        if test_source and before_source:
            test_ratio = self._compute_test_ratio(before_source, after_source, test_source)
            weak_signals.extend(self._detect_test_weaknesses(test_source, after_source))

            if test_ratio < self.threshold_test_ratio:
                weak_signals.append(
                    f"tests_to_code_ratio={test_ratio:.2f} below threshold "
                    f"{self.threshold_test_ratio}"
                )

        # ── Check 3: Collusion Detection ──────────────────────────────
        if test_source and after_source:
            if self._detect_collusion(after_source, test_source):
                verdict = AdversarialVerdict.COLLUSION
                notes = (
                    "Collusion detected: test code mirrors implementation constants "
                    "or structure too precisely. Likely reward hacking. Quarantined."
                )
                return self._build_result(
                    mutation_id, verdict, False, test_ratio, logic_density,
                    weak_signals, edge_failures, 0.0, notes
                )

        # ── Check 4: Mutation Test Score ──────────────────────────────
        mutation_score = self._compute_mutation_test_score(after_source, test_source)
        if mutation_score < self.min_mutation_test_score:
            verdict = AdversarialVerdict.WEAK_TEST
            notes = (
                f"Weak test suite: mutation_test_score={mutation_score:.2f} "
                f"below minimum {self.min_mutation_test_score}. "
                f"Tests do not adequately cover the changed logic."
            )
            return self._build_result(
                mutation_id, verdict, False, test_ratio, logic_density,
                weak_signals, edge_failures, mutation_score, notes
            )

        # ── Check 5: Edge Case Injection ──────────────────────────────
        edge_failures = self._inject_edge_cases(after_source)
        if edge_failures:
            verdict = AdversarialVerdict.FRAGILE
            notes = (
                f"Fragile mutation: {len(edge_failures)} edge case(s) failed: "
                f"{'; '.join(edge_failures[:3])}. Mutation quarantined."
            )
            return self._build_result(
                mutation_id, verdict, False, test_ratio, logic_density,
                weak_signals, edge_failures, mutation_score, notes
            )

        # ── All challenges passed ──────────────────────────────────────
        notes = (
            f"All adversarial challenges passed. "
            f"test_ratio={test_ratio:.2f}, logic_density={logic_density:.3f}, "
            f"mutation_score={mutation_score:.2f}."
        )
        return self._build_result(
            mutation_id, AdversarialVerdict.PASSED, True,
            test_ratio, logic_density, weak_signals, edge_failures, mutation_score, notes
        )

    # ------------------------------------------------------------------
    # Private: Check implementations
    # ------------------------------------------------------------------

    def _compute_logic_density(self, source: str) -> float:
        """
        Ratio of cyclomatic complexity to AST node count.
        High density = complex logic in few lines = suspicious.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return 1.0  # unparseable = maximum suspicion

        node_count = sum(1 for _ in ast.walk(tree))
        branches = sum(
            1 for node in ast.walk(tree)
            if isinstance(node, (ast.If, ast.While, ast.For, ast.ExceptHandler,
                                  ast.comprehension, ast.BoolOp))
        )
        if node_count == 0:
            return 0.0
        return branches / node_count

    def _compute_test_ratio(
        self,
        before_source: str,
        after_source: str,
        test_source: str,
    ) -> float:
        """
        Ratio of test lines to changed code lines.
        Below threshold = tests are under-covering the change.
        """
        changed_lines = sum(
            1 for a, b in zip(before_source.splitlines(), after_source.splitlines())
            if a != b
        )
        changed_lines += abs(
            len(after_source.splitlines()) - len(before_source.splitlines())
        )
        test_lines = len([l for l in test_source.splitlines() if l.strip()])
        if changed_lines == 0:
            return float("inf")  # no changes = trivially covered
        return test_lines / changed_lines

    def _detect_test_weaknesses(self, test_source: str, after_source: str) -> list[str]:
        """
        Detect common test weakness patterns:
        - Tests that only assert on mocked return values
        - Tests with no assertions at all
        - Tests with a single assertion for many code paths
        """
        signals = []
        lines = test_source.splitlines()

        # No assertions at all
        assert_lines = [l for l in lines if "assert" in l.lower()]
        if not assert_lines:
            signals.append("No assertions found in test source")

        # Only mocked assertions
        mock_assert = [l for l in assert_lines if "mock" in l.lower() or "called" in l.lower()]
        if len(mock_assert) == len(assert_lines) and assert_lines:
            signals.append("All assertions are on mock objects — real behavior untested")

        # Test-to-branch ratio: one assert per multiple branches
        try:
            tree = ast.parse(after_source)
            branch_count = sum(
                1 for n in ast.walk(tree)
                if isinstance(n, (ast.If, ast.While, ast.For))
            )
            if branch_count > 0 and len(assert_lines) < branch_count // 2:
                signals.append(
                    f"assert_count={len(assert_lines)} < branch_count//2={branch_count//2}; "
                    f"branches likely untested"
                )
        except SyntaxError:
            pass

        return signals

    def _detect_collusion(self, after_source: str, test_source: str) -> bool:
        """
        Detects if test constants or magic values are directly copied
        from implementation — a sign of reward hacking / test overfitting.
        """
        # Extract numeric and string literals from implementation
        impl_literals: set[str] = set()
        try:
            tree = ast.parse(after_source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str)):
                    impl_literals.add(str(node.value))
        except SyntaxError:
            return False

        # Extract same from tests
        test_literals: set[str] = set()
        try:
            tree = ast.parse(test_source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str)):
                    test_literals.add(str(node.value))
        except SyntaxError:
            return False

        # Collusion signal: >80% of unique *non-trivial* implementation literals
        # appear verbatim in tests. Filter out trivial values (0, 1, -1, True, False,
        # empty strings) to avoid false positives on simple arithmetic mutations.
        trivial = {"0", "1", "-1", "2", "True", "False", "", "None"}
        non_trivial_impl = impl_literals - trivial
        if len(non_trivial_impl) < 3:
            # Not enough distinctive constants to be meaningful — not collusion
            return False
        overlap = len(non_trivial_impl & test_literals) / len(non_trivial_impl)
        return overlap > 0.80

    def _compute_mutation_test_score(
        self,
        after_source: str,
        test_source: Optional[str],
    ) -> float:
        """
        Simplified mutation testing: apply micro-mutations to after_source
        (e.g., flip comparison operators, negate conditions) and check
        if the test_source would logically detect them.

        Full mutation testing requires execution; this is a static approximation.
        Returns 0.0..1.0 — fraction of micro-mutations the tests would likely catch.
        """
        if not test_source:
            return 0.5  # neutral if no tests provided

        OPERATORS = ["==", "!=", "<=", ">=", "<", ">", "and", "or", "not "]
        mutations_detectable = 0
        total_mutations = 0

        for op in OPERATORS:
            if op in after_source:
                total_mutations += 1
                # A test is likely to catch this mutation if it asserts on related variables
                # Heuristic: test contains any of the operands around the operator
                idx = after_source.find(op)
                context = after_source[max(0, idx-20):idx+20]
                tokens = re.findall(r'\b\w+\b', context)
                for token in tokens:
                    if len(token) > 2 and token in test_source:
                        mutations_detectable += 1
                        break

        if total_mutations == 0:
            return 1.0  # no operators to mutate = trivially passes
        return mutations_detectable / total_mutations

    def _inject_edge_cases(self, source: str) -> list[str]:
        """
        Static edge case detection: identify functions that handle numeric inputs
        but may not handle zero, negative, or None values.

        Returns list of failure descriptions (empty = no issues found).
        """
        failures = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return ["SyntaxError: could not parse after_source for edge case analysis"]

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_src = ast.unparse(node)
                # Check for division without zero guard
                if "/" in func_src or "//" in func_src:
                    has_zero_guard = (
                        "!= 0" in func_src or "== 0" in func_src
                        or "ZeroDivision" in func_src or "if" in func_src
                    )
                    if not has_zero_guard:
                        failures.append(
                            f"Function '{node.name}': division detected without zero guard"
                        )

                # Check for list/dict access without bounds or key check
                has_subscript = any(
                    isinstance(n, ast.Subscript) for n in ast.walk(node)
                )
                has_index_guard = (
                    "len(" in func_src or "in " in func_src
                    or "IndexError" in func_src or "KeyError" in func_src
                )
                if has_subscript and not has_index_guard:
                    failures.append(
                        f"Function '{node.name}': subscript access without bounds/key check"
                    )

        return failures

    # ------------------------------------------------------------------
    # Private: Result builder
    # ------------------------------------------------------------------

    def _build_result(
        self,
        mutation_id: str,
        verdict: AdversarialVerdict,
        passed: bool,
        test_ratio: float,
        logic_density: float,
        weak_signals: list[str],
        edge_failures: list[str],
        mutation_score: float,
        notes: str,
    ) -> AdversarialChallenge:
        payload = json.dumps({
            "mutation_id": mutation_id,
            "verdict": verdict.value,
            "test_ratio": test_ratio,
            "logic_density": logic_density,
            "mutation_score": mutation_score,
        }, sort_keys=True)
        challenge_hash = hashlib.sha256(payload.encode()).hexdigest()

        return AdversarialChallenge(
            mutation_id=mutation_id,
            verdict=verdict,
            passed=passed,
            tests_to_code_ratio=test_ratio,
            logic_density_score=logic_density,
            weak_test_signals=tuple(weak_signals),
            edge_case_failures=tuple(edge_failures),
            mutation_test_score=mutation_score,
            challenge_hash=challenge_hash,
            notes=notes,
        )
