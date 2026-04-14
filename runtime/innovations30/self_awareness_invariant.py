# SPDX-License-Identifier: Apache-2.0
"""Innovation #28 — Self-Awareness Invariant (SELF-AWARE).
Constitutional rule SELF-AWARE-0: no mutation may reduce the observability
surface of the system's self-monitoring infrastructure.
The system cannot optimize away its own transparency.

Constitutional invariants:
    SELF-AWARE-0      — no mutation may remove observability calls from
                        protected monitoring modules; violation = DENY
    SELF-AWARE-DETERM-0 — evaluate() MUST return identical verdict_digest
                          for identical (mutation_id, diff_text, changed_files)
    SELF-AWARE-AUDIT-0  — every SelfAwarenessVerdict MUST carry a non-empty
                          verdict_digest and persist to audit trail when path set

Additions (v1.1 — Phase 113):
    SELF_AWARE_INVARIANTS   — Hard-class invariant registry
    self_aware_guard()      — fail-closed governance gate enforcement
    to_ledger_row()         — JSONL serialisation for append-only audit trail
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
SEAWIN_INV_CHAIN: str = "SEAWIN-INV-CHAIN"


class SelfAwarenessInvariantViolation(RuntimeError):
    """Raised when a Self Awareness Invariant constitutional invariant is breached."""



# ── Protected self-monitoring modules ───────────────────────────────────────
_DEFAULT_PROTECTED: frozenset[str] = frozenset([
    "runtime/metrics.py",
    "runtime/invariants.py",
    "security/ledger/journal.py",
    "runtime/governance/health_aggregator.py",
    "runtime/preflight.py",
    "runtime/constitution.py",
])

OBSERVABILITY_REDUCTION_PATTERNS: list[str] = [
    r"metrics\.log\(",
    r"journal\.append",
    r"verify_journal_integrity",
    r"verify_all\(",
    r"boot_sanity_check",
    r"log\.warning\(",
    r"log\.error\(",
]

SELF_AWARE_INVARIANTS: dict[str, str] = {
    "SELF-AWARE-0": (
        "No mutation may remove observability calls from protected monitoring modules. "
        "Violations are constitutional DENY — the system cannot optimize away its transparency."
    ),
    "SELF-AWARE-DETERM-0": (
        "evaluate() MUST return identical verdict_digest for identical "
        "(mutation_id, diff_text, changed_files) inputs."
    ),
    "SELF-AWARE-AUDIT-0": (
        "Every SelfAwarenessVerdict MUST carry a non-empty verdict_digest. "
        "When audit_path is set, verdicts MUST persist to append-only JSONL."
    ),
}


@dataclass
class SelfAwarenessVerdict:
    """Tamper-evident self-awareness evaluation result [SELF-AWARE-AUDIT-0]."""
    mutation_id: str
    passed: bool
    violations: list = field(default_factory=list)
    protected_module_touched: bool = False
    removed_observability_calls: list = field(default_factory=list)
    surface_score: float = 1.0
    verdict_digest: str = ""
    timestamp: float = field(default_factory=time.time)
    rule_id: str = "SELF-AWARE-0"
    invariants_verified: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.verdict_digest:
            payload = (
                f"{self.mutation_id}:{self.passed}:{self.rule_id}:"
                f"{sorted(self.violations)}:{self.surface_score:.4f}"
            )
            self.verdict_digest = (
                "sha256:" + hashlib.sha256(payload.encode()).hexdigest()[:16]
            )
        if not self.invariants_verified:
            self.invariants_verified = list(SELF_AWARE_INVARIANTS.keys())

    def to_ledger_row(self) -> str:
        """Single-line JSONL for append-only audit trail [SELF-AWARE-AUDIT-0]."""
        d = asdict(self)
        d.pop("timestamp", None)
        return json.dumps(d, sort_keys=True)


def self_aware_guard(verdict: SelfAwarenessVerdict) -> None:
    """Fail-closed enforcement for governance gate [SELF-AWARE-0].

    Raises RuntimeError if verdict is missing digest or has inconsistent state.
    """
    if not verdict.verdict_digest:
        raise RuntimeError("SELF-AWARE-AUDIT-0: verdict_digest MUST be non-empty.")
    if verdict.violations and verdict.passed:
        raise RuntimeError(
            "SELF-AWARE-0: verdict.passed=True but violations are non-empty — "
            "inconsistent verdict state."
        )
    if not verdict.violations and not verdict.passed:
        raise RuntimeError(
            "SELF-AWARE-0: verdict.passed=False but violations are empty — "
            "inconsistent verdict state."
        )


class SelfAwarenessInvariant:
    """Enforces SELF-AWARE-0: protect self-monitoring infrastructure.

    Constitutional guarantees (Phase 113):
        SELF-AWARE-0        : violations on protected modules → DENY
        SELF-AWARE-DETERM-0 : identical inputs → identical digest
        SELF-AWARE-AUDIT-0  : verdict_digest always present; audit trail persisted
    """

    def __init__(
        self,
        audit_path: Path | None = None,
        extra_protected: frozenset[str] | None = None,
    ) -> None:
        self._protected: set[str] = set(_DEFAULT_PROTECTED)
        if extra_protected:
            self._protected.update(extra_protected)
        self._audit_path = Path(audit_path) if audit_path else None
        self._violation_count: int = 0
        self._evaluation_count: int = 0

    def register_protected_module(self, path: str) -> None:
        """Expand the protected observability surface at runtime."""
        self._protected.add(path)

    def evaluate(
        self,
        mutation_id: str,
        diff_text: str,
        changed_files: list[str],
    ) -> SelfAwarenessVerdict:
        """Evaluate a mutation diff against SELF-AWARE-0.

        [SELF-AWARE-DETERM-0] identical inputs → identical verdict_digest.
        [SELF-AWARE-AUDIT-0]  audit trail persisted when path is set.
        """
        self._evaluation_count += 1
        violations: list[str] = []
        removed_calls: list[str] = []

        touched_protected = sorted([
            pm for pm in self._protected
            if any(pm in str(f) for f in changed_files)
        ])
        protected_touched = bool(touched_protected)

        minus_lines = "\n".join(
            l[1:] for l in diff_text.splitlines()
            if l.startswith("-") and not l.startswith("---")
        )
        for pattern in OBSERVABILITY_REDUCTION_PATTERNS:
            matches = re.findall(pattern, minus_lines)
            if matches:
                removed_calls.extend(matches[:2])

        if protected_touched and removed_calls:
            violations.append(
                f"SELF-AWARE-0: removes {len(removed_calls)} observability call(s) "
                f"from {touched_protected}. Patterns: {removed_calls[:3]}."
            )

        n_protected = len(self._protected)
        n_touched = len(touched_protected)
        surface_score = (
            round(1.0 - (n_touched / n_protected), 4) if n_protected else 1.0
        )

        if violations:
            self._violation_count += 1

        verdict = SelfAwarenessVerdict(
            mutation_id=mutation_id,
            passed=len(violations) == 0,
            violations=violations,
            protected_module_touched=protected_touched,
            removed_observability_calls=removed_calls,
            surface_score=surface_score,
        )

        if self._audit_path is not None:
            self._persist(verdict)

        return verdict

    def protected_surface_score(self, changed_files: list[str]) -> float:
        n_protected = len(self._protected)
        if n_protected == 0:
            return 1.0
        touched = sum(
            1 for pm in self._protected
            if any(pm in str(f) for f in changed_files)
        )
        return round(1.0 - (touched / n_protected), 4)

    def summary(self) -> dict[str, Any]:
        return {
            "rule_id": "SELF-AWARE-0",
            "protected_modules": sorted(self._protected),
            "protected_module_count": len(self._protected),
            "total_evaluations": self._evaluation_count,
            "total_violations": self._violation_count,
            "violation_rate": (
                round(self._violation_count / self._evaluation_count, 4)
                if self._evaluation_count else 0.0
            ),
            "observability_reduction_patterns": len(OBSERVABILITY_REDUCTION_PATTERNS),
            "invariants": list(SELF_AWARE_INVARIANTS.keys()),
        }

    def _persist(self, verdict: SelfAwarenessVerdict) -> None:
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self._audit_path.open("a") as f:
            f.write(verdict.to_ledger_row() + "\n")


PROTECTED_OBSERVABILITY_MODULES = _DEFAULT_PROTECTED

# ── Chain-linkage scaffold (hardening pass — prev_digest + _append_event) ─────
import hashlib as _hashlib
import json as _json


_MODULE_PREV_DIGEST: str = "genesis"   # prev_digest chain head for this module


def _append_event(event: dict, ledger_path: str = "") -> None:
    """Module-level append-only JSONL event stub [CED-INV-AUDIT, CED-INV-CHAIN].

    Writes a chain-linked record to ledger_path (or discards if empty).
    Full integration deferred to per-module deep-dive phase.
    """
    global _MODULE_PREV_DIGEST
    if not ledger_path:
        return
    import dataclasses as _dc
    from pathlib import Path as _Path
    row = event if isinstance(event, dict) else (
        _dc.asdict(event) if hasattr(event, '__dataclass_fields__') else {}
    )
    row["prev_digest"] = _MODULE_PREV_DIGEST
    digest_payload = _json.dumps(row, sort_keys=True).encode()
    row["event_digest"] = "sha256:" + _hashlib.sha256(digest_payload).hexdigest()
    p = _Path(ledger_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(_json.dumps(row, sort_keys=True) + "\n")
    _MODULE_PREV_DIGEST = row["event_digest"]


__all__ = [
    "SelfAwarenessInvariant", "SelfAwarenessVerdict", "self_aware_guard",
    "SELF_AWARE_INVARIANTS", "PROTECTED_OBSERVABILITY_MODULES",
    "OBSERVABILITY_REDUCTION_PATTERNS",
]
