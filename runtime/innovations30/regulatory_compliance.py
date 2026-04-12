# SPDX-License-Identifier: Apache-2.0
"""Innovation #23 — Regulatory Compliance Layer.
EU AI Act, NIST AI RMF as machine-enforceable governance gates.
"""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import hashlib
import hmac

# Hardening scaffold — injected by fix/senior-deep-dive-hardening
RECO_INV_CHAIN: str = "RECO-INV-CHAIN"
RECO_LEDGER_DEFAULT: str = "data/regulatory_compliance_events.jsonl"


class RegulatoryComplianceViolation(RuntimeError):
    """Raised when a Regulatory Compliance constitutional invariant is breached."""



@dataclass
class ComplianceRule:
    rule_id: str
    framework: str      # "EU_AI_ACT" | "NIST_AI_RMF" | "CUSTOM"
    article: str        # e.g. "EU_AI_ACT_Art13"
    requirement: str
    prohibited_patterns: list[str]
    severity: str = "blocking"
    jurisdiction: str = "global"
    enforcement_date: str = "2024-08-01"

@dataclass
class ComplianceViolation:
    rule_id: str
    framework: str
    article: str
    mutation_id: str
    violation_description: str
    remediation_guidance: str

@dataclass
class ComplianceReport:
    mutation_id: str
    passed: bool
    violations: list[ComplianceViolation]
    checked_frameworks: list[str]
    report_digest: str = ""

    def __post_init__(self):
        if not self.report_digest:
            payload = f"{self.mutation_id}:{self.passed}:{len(self.violations)}"
            self.report_digest = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


# Built-in compliance rules
BUILTIN_RULES: list[ComplianceRule] = [
    ComplianceRule(
        rule_id="EU-AIA-ART13-TRANSPARENCY",
        framework="EU_AI_ACT",
        article="Article 13 — Transparency",
        requirement="AI systems must maintain human-interpretable audit trails",
        prohibited_patterns=["delete_audit_trail", "bypass_logging",
                              "remove_ledger", "disable_metrics"],
        severity="blocking",
    ),
    ComplianceRule(
        rule_id="EU-AIA-ART9-RISKMANAGEMENT",
        framework="EU_AI_ACT",
        article="Article 9 — Risk Management",
        requirement="Risk management systems must not be disabled",
        prohibited_patterns=["disable_governance", "skip_gate",
                              "bypass_invariant", "remove_health_check"],
        severity="blocking",
    ),
    ComplianceRule(
        rule_id="NIST-AI-RMF-GOVERN1",
        framework="NIST_AI_RMF",
        article="GOVERN 1 — Accountability",
        requirement="Human oversight mechanisms must remain operational",
        prohibited_patterns=["remove_human_gate", "disable_human_0",
                              "bypass_signoff", "remove_approval"],
        severity="blocking",
    ),
    ComplianceRule(
        rule_id="NIST-AI-RMF-MEASURE2",
        framework="NIST_AI_RMF",
        article="MEASURE 2 — Testing",
        requirement="Testing and evaluation must not be reduced",
        prohibited_patterns=["remove_test", "skip_test", "delete_test",
                              "xfail_test", "comment_out_test"],
        severity="warning",
    ),
]


class RegulatoryComplianceEngine:
    """Evaluates mutations against regulatory compliance rules."""

    def __init__(self, rules: list[ComplianceRule] | None = None,
                 ledger_path: Path = Path("data/compliance_violations.jsonl")):
        self.rules = rules or BUILTIN_RULES
        self.ledger_path = Path(ledger_path)

    def evaluate(self, mutation_id: str, diff_text: str,
                  mutation_intent: str) -> ComplianceReport:
        violations = []
        combined = (diff_text + " " + mutation_intent).lower()
        checked_frameworks = list({r.framework for r in self.rules})

        for rule in self.rules:
            for pattern in rule.prohibited_patterns:
                if pattern.lower() in combined:
                    v = ComplianceViolation(
                        rule_id=rule.rule_id,
                        framework=rule.framework,
                        article=rule.article,
                        mutation_id=mutation_id,
                        violation_description=(
                            f"Mutation contains pattern '{pattern}' which may violate "
                            f"{rule.article}: {rule.requirement}"
                        ),
                        remediation_guidance=(
                            f"Ensure {rule.requirement.lower()}. "
                            f"If this is a legitimate exception, document it explicitly "
                            f"and obtain human approval with compliance citation."
                        ),
                    )
                    violations.append(v)
                    break  # one violation per rule

        report = ComplianceReport(
            mutation_id=mutation_id,
            passed=all(r.severity != "blocking" or
                        r.rule_id not in [v.rule_id for v in violations]
                        for r in self.rules),
            violations=violations,
            checked_frameworks=checked_frameworks,
        )
        if violations:
            self._persist_violations(violations)
        return report

    def _persist_violations(self, violations: list[ComplianceViolation]) -> None:
        import dataclasses
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a") as f:
            for v in violations:
                f.write(json.dumps(dataclasses.asdict(v)) + "\n")


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


__all__ = ["RegulatoryComplianceEngine", "ComplianceReport", "ComplianceViolation",
           "ComplianceRule", "BUILTIN_RULES"]
