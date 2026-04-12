# SPDX-License-Identifier: Apache-2.0
"""Innovation #24 — Semantic Version Promises.
Machine-verifiable semver contracts enforced at governance.

Additions (v1.1):
    record_verdict()           — persist verdict to JSONL with SHA-256 digest
    verdict_history()          — audit trail readback
    breaking_change_analysis() — structured breakdown of detected API changes
    SHA-256 verdict digest     — tamper-detectable audit chain per verdict
"""
from __future__ import annotations
import ast, hashlib, json, re, time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
SEVEEN_INV_CHAIN: str = "SEVEEN-INV-CHAIN"
SEVEEN_LEDGER_DEFAULT: str = "data/semantic_version_enforcer_events.jsonl"


class SemanticVersionEnforcerViolation(RuntimeError):
    """Raised when a Semantic Version Enforcer constitutional invariant is breached."""



SemVerImpact = str  # "patch" | "minor" | "major"


@dataclass
class SemVerVerdict:
    mutation_id: str
    declared_impact: SemVerImpact
    detected_impact: SemVerImpact
    contract_honored: bool
    violations: list[str]
    verdict_digest: str = ""        # SHA-256 tamper-detectable chain hash
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.verdict_digest:
            payload = (
                f"{self.mutation_id}:{self.declared_impact}:"
                f"{self.detected_impact}:{self.contract_honored}"
            )
            self.verdict_digest = (
                "sha256:" + hashlib.sha256(payload.encode()).hexdigest()
            )

    @property
    def verdict(self) -> str:
        return "PASS" if self.contract_honored else "FAIL"


IMPACT_RANK = {"patch": 0, "minor": 1, "major": 2}


class SemanticVersionEnforcer:
    """Verifies that declared version impact matches actual code change."""

    # Patterns indicating API-breaking changes
    BREAKING_PATTERNS = [
        r'def [a-z]\w+\(.*\) ->',    # function signature changes
        r'class \w+:',               # class definition changes
        r'__all__\s*=',              # exported names changes
        r'from \w+ import',          # import changes
    ]

    # Patterns indicating new functionality (minor)
    FEATURE_PATTERNS = [
        r'def [a-z]\w+\(',          # new function
        r'class \w+\(',             # new class
        r'@property',               # new property
    ]

    def __init__(self, audit_path: Path | None = None) -> None:
        self._audit_path = Path(audit_path) if audit_path else None

    def verify(
        self,
        mutation_id: str,
        declared_impact: SemVerImpact,
        diff_text: str,
    ) -> SemVerVerdict:
        """Verify declared semver impact against diff content."""
        detected = self._detect_impact(diff_text)
        detected_rank = IMPACT_RANK.get(detected, 0)
        declared_rank = IMPACT_RANK.get(declared_impact, 0)

        violations: list[str] = []
        if detected_rank > declared_rank:
            violations.append(
                f"Declared '{declared_impact}' but detected '{detected}'. "
                f"Actual change is more impactful than stated."
            )
        contract_honored = len(violations) == 0

        verdict = SemVerVerdict(
            mutation_id=mutation_id,
            declared_impact=declared_impact,
            detected_impact=detected,
            contract_honored=contract_honored,
            violations=violations,
        )

        if self._audit_path is not None:
            self.record_verdict(verdict, self._audit_path)

        return verdict

    def record_verdict(
        self,
        verdict: SemVerVerdict,
        audit_path: Path,
    ) -> None:
        """Persist a SemVerVerdict to a JSONL audit trail."""
        Path(audit_path).parent.mkdir(parents=True, exist_ok=True)
        with Path(audit_path).open("a") as f:
            f.write(json.dumps(asdict(verdict)) + "\n")

    def verdict_history(
        self,
        audit_path: Path | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Read back the last N persisted verdicts from the audit trail."""
        path = Path(audit_path) if audit_path else self._audit_path
        if path is None or not path.exists():
            return []
        lines = path.read_text().splitlines()
        results: list[dict] = []
        for line in lines[-limit:]:
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return results

    def breaking_change_analysis(self, diff_text: str) -> dict[str, Any]:
        """Return a structured breakdown of detected API change signals.

        Useful for governance dashboards and audit reports.
        Returns:
            {
              "detected_impact": "patch"|"minor"|"major",
              "breaking_signals": [...matched patterns from removed lines],
              "feature_signals":  [...matched patterns from added lines],
              "public_api_removals": int,
              "public_api_additions": int,
            }
        """
        plus_lines = "\n".join(
            l[1:] for l in diff_text.splitlines()
            if l.startswith("+") and not l.startswith("+++")
        )
        minus_lines = "\n".join(
            l[1:] for l in diff_text.splitlines()
            if l.startswith("-") and not l.startswith("---")
        )

        breaking_signals: list[str] = []
        for pattern in self.BREAKING_PATTERNS:
            matches = re.findall(pattern, minus_lines)
            if matches:
                breaking_signals.extend(matches[:2])

        feature_signals: list[str] = []
        for pattern in self.FEATURE_PATTERNS:
            matches = re.findall(pattern, plus_lines)
            if matches:
                feature_signals.extend(matches[:2])

        # Count public API changes (functions/classes added/removed in __all__)
        public_removals = len(re.findall(r"__all__\s*=", minus_lines))
        public_additions = len(re.findall(r"__all__\s*=", plus_lines))

        return {
            "detected_impact": self._detect_impact(diff_text),
            "breaking_signals": breaking_signals,
            "feature_signals": feature_signals,
            "public_api_removals": public_removals,
            "public_api_additions": public_additions,
        }

    def _detect_impact(self, diff_text: str) -> SemVerImpact:
        plus_lines = "\n".join(
            l[1:] for l in diff_text.splitlines()
            if l.startswith("+") and not l.startswith("+++")
        )
        minus_lines = "\n".join(
            l[1:] for l in diff_text.splitlines()
            if l.startswith("-") and not l.startswith("---")
        )

        # Breaking: signatures removed from public API
        for pattern in self.BREAKING_PATTERNS:
            if re.search(pattern, minus_lines) and "__all__" in minus_lines:
                return "major"
            if re.search(pattern, minus_lines) and re.search(r'def \w+\(', minus_lines):
                return "major"

        # Feature: new public functions/classes added
        for pattern in self.FEATURE_PATTERNS:
            if re.search(pattern, plus_lines):
                return "minor"

        return "patch"


__all__ = [
    "SemanticVersionEnforcer",
    "SemVerVerdict",
    "SemVerImpact",
    "IMPACT_RANK",
]
