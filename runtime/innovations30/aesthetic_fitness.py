# SPDX-License-Identifier: Apache-2.0
"""Innovation #9 — Aesthetic Fitness Signal.

Measures code readability, naming quality, structural clarity.
A system that only optimizes correctness accumulates cognitive debt.
"""
from __future__ import annotations
import ast, re, math
from dataclasses import dataclass
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
AEFI_INV_CHAIN: str = "AEFI-INV-CHAIN"
AEFI_LEDGER_DEFAULT: str = "data/aesthetic_fitness_events.jsonl"


class AestheticFitnessViolation(RuntimeError):
    """Raised when a Aesthetic Fitness constitutional invariant is breached."""



AESTHETIC_WEIGHT: float = 0.05   # initial weight in composite fitness

@dataclass
class AestheticScore:
    mutation_id: str
    function_length_score: float    # shorter functions → higher score
    naming_quality_score: float     # meaningful names vs single-char
    nesting_depth_score: float      # shallower nesting → higher score
    comment_density_score: float    # appropriate comment coverage
    overall_aesthetic: float
    dimension_breakdown: dict[str, float]


class AestheticFitnessScorer:
    """Scores code beauty as a first-class fitness signal."""

    MAX_IDEAL_FUNCTION_LINES: int = 25
    MAX_IDEAL_NESTING: int = 3
    MIN_COMMENT_RATIO: float = 0.05

    def score(self, mutation_id: str, source_before: str,
              source_after: str) -> AestheticScore:
        """Score aesthetic improvement: after vs before."""
        before_aesthetic = self._score_source(source_before)
        after_aesthetic = self._score_source(source_after)

        # Score is improvement delta normalized
        delta = {k: after_aesthetic[k] - before_aesthetic[k]
                 for k in after_aesthetic}

        fn_score     = self._normalize_delta(delta.get("avg_function_length_score", 0))
        name_score   = self._normalize_delta(delta.get("naming_score", 0))
        nest_score   = self._normalize_delta(delta.get("nesting_score", 0))
        comment_score = self._normalize_delta(delta.get("comment_score", 0))

        overall = (fn_score * 0.30 + name_score * 0.30
                   + nest_score * 0.25 + comment_score * 0.15)

        return AestheticScore(
            mutation_id=mutation_id,
            function_length_score=round(fn_score, 4),
            naming_quality_score=round(name_score, 4),
            nesting_depth_score=round(nest_score, 4),
            comment_density_score=round(comment_score, 4),
            overall_aesthetic=round(overall, 4),
            dimension_breakdown={
                "function_length": round(fn_score, 4),
                "naming_quality": round(name_score, 4),
                "nesting_depth": round(nest_score, 4),
                "comment_density": round(comment_score, 4),
            },
        )

    def _score_source(self, source: str) -> dict[str, float]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return {"avg_function_length_score": 0.0, "naming_score": 0.5,
                    "nesting_score": 0.5, "comment_score": 0.5}

        fn_lengths = []
        max_depths = []
        var_names = []

        class Visitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                fn_lengths.append(node.end_lineno - node.lineno + 1
                                   if hasattr(node, "end_lineno") else 10)
                self.generic_visit(node)

            def visit_Name(self, node):
                if isinstance(node.ctx, ast.Store):
                    var_names.append(node.id)

        Visitor().visit(tree)

        # Function length score
        avg_len = (sum(fn_lengths) / len(fn_lengths)) if fn_lengths else 10
        fn_score = max(0.0, 1.0 - (avg_len - self.MAX_IDEAL_FUNCTION_LINES) /
                       self.MAX_IDEAL_FUNCTION_LINES) if avg_len > self.MAX_IDEAL_FUNCTION_LINES else 1.0

        # Naming quality: penalize single-char names that aren't loop vars
        bad_names = sum(1 for n in var_names if len(n) == 1 and n not in "ijk")
        naming_score = max(0.0, 1.0 - bad_names / max(1, len(var_names)))

        # Nesting depth (simplified)
        lines = source.splitlines()
        max_indent = max((len(l) - len(l.lstrip())) // 4
                         for l in lines if l.strip()) if lines else 0
        nesting_score = max(0.0, 1.0 - max(0, max_indent - self.MAX_IDEAL_NESTING) / 5)

        # Comment density
        comment_lines = sum(1 for l in lines if l.strip().startswith("#"))
        code_lines = sum(1 for l in lines if l.strip() and not l.strip().startswith("#"))
        comment_ratio = comment_lines / max(1, code_lines)
        comment_score = min(1.0, comment_ratio / self.MIN_COMMENT_RATIO) if comment_ratio < 0.25 else 1.0

        return {"avg_function_length_score": fn_score, "naming_score": naming_score,
                "nesting_score": nesting_score, "comment_score": comment_score}

    def _normalize_delta(self, delta: float) -> float:
        return max(0.0, min(1.0, 0.5 + delta))


__all__ = ["AestheticFitnessScorer", "AestheticScore", "AESTHETIC_WEIGHT"]
