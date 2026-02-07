# SPDX-License-Identifier: Apache-2.0
"""
Constitutional rules governing ADAAD mutation safety.

The constitution is versioned, tiered, auditable, and evolvable.
Every mutation passes through constitutional evaluation before execution.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List

from app.agents.mutation_request import MutationRequest
from runtime import metrics

CONSTITUTION_VERSION = "0.1.0"
ELEMENT_ID = "Earth"


class Severity(Enum):
    """Rule enforcement severity levels."""

    BLOCKING = "blocking"
    WARNING = "warning"
    ADVISORY = "advisory"


class Tier(Enum):
    """Agent trust tiers for graduated autonomy."""

    PRODUCTION = 0
    STABLE = 1
    SANDBOX = 2


@dataclass
class Rule:
    """Constitutional rule definition."""

    name: str
    enabled: bool
    severity: Severity
    tier_overrides: Dict[Tier, Severity]
    reason: str
    validator: Callable[[MutationRequest], Dict[str, Any]]


def _validate_single_file(request: MutationRequest) -> Dict[str, Any]:
    """Enforce single-file mutation scope."""
    from runtime.preflight import _extract_targets

    targets = _extract_targets(request)
    if len(targets) == 1:
        return {"ok": True, "target_count": 1}
    return {
        "ok": False,
        "reason": "multi_file_mutation",
        "target_count": len(targets),
        "targets": [str(target) for target in targets],
    }


def _validate_ast(request: MutationRequest) -> Dict[str, Any]:
    """Validate Python AST parsability."""
    from runtime.preflight import _ast_check, _extract_source, _extract_targets

    targets = _extract_targets(request)
    if not targets:
        return {"ok": True, "reason": "no_targets"}

    target = next(iter(targets))
    source = _extract_source(request, target)
    return _ast_check(target, source)


def _validate_imports(request: MutationRequest) -> Dict[str, Any]:
    """Smoke test import validity."""
    from runtime.preflight import _extract_source, _extract_targets, _import_smoke_check

    targets = _extract_targets(request)
    if not targets:
        return {"ok": True, "reason": "no_targets"}

    target = next(iter(targets))
    source = _extract_source(request, target)
    return _import_smoke_check(target, source)


def _validate_signature(request: MutationRequest) -> Dict[str, Any]:
    """Verify cryptographic signature."""
    from security import cryovant

    signature = request.signature or ""
    if cryovant.verify_signature(signature):
        return {"ok": True, "method": "verified"}
    if cryovant.dev_signature_allowed(signature):
        return {"ok": True, "method": "dev_signature"}
    return {"ok": False, "reason": "invalid_signature"}


def _validate_no_banned_tokens(request: MutationRequest) -> Dict[str, Any]:
    """Block dangerous code patterns."""
    from runtime.preflight import _extract_source, _extract_targets

    banned = ["eval(", "exec(", "os.system(", "__import__", "compile("]
    targets = _extract_targets(request)
    if not targets:
        return {"ok": True}

    target = next(iter(targets))
    source = _extract_source(request, target)
    if not source:
        return {"ok": True}

    found = [token for token in banned if token in source]
    if found:
        return {"ok": False, "reason": "banned_tokens", "found": found}
    return {"ok": True}


def _validate_lineage(_: MutationRequest) -> Dict[str, Any]:
    """Ensure lineage continuity (stub for now)."""
    return {"ok": True, "reason": "not_yet_implemented"}


def _validate_complexity(_: MutationRequest) -> Dict[str, Any]:
    """Check complexity delta (stub for now)."""
    return {"ok": True, "reason": "not_yet_implemented"}


def _validate_coverage(_: MutationRequest) -> Dict[str, Any]:
    """Verify test coverage maintained (stub for now)."""
    return {"ok": True, "reason": "not_yet_implemented"}


def _validate_mutation_rate(_: MutationRequest) -> Dict[str, Any]:
    """Check mutation rate limits (stub for now)."""
    return {"ok": True, "reason": "not_yet_implemented"}


def _validate_resources(_: MutationRequest) -> Dict[str, Any]:
    """Enforce resource bounds (stub for now)."""
    return {"ok": True, "reason": "not_yet_implemented"}


RULES: List[Rule] = [
    Rule(
        name="single_file_scope",
        enabled=True,
        severity=Severity.BLOCKING,
        tier_overrides={Tier.SANDBOX: Severity.WARNING},
        reason="Android memory constraints; reduces blast radius",
        validator=_validate_single_file,
    ),
    Rule(
        name="ast_validity",
        enabled=True,
        severity=Severity.BLOCKING,
        tier_overrides={},
        reason="Prevent syntax errors from breaking runtime",
        validator=_validate_ast,
    ),
    Rule(
        name="import_smoke_test",
        enabled=True,
        severity=Severity.WARNING,
        tier_overrides={Tier.PRODUCTION: Severity.BLOCKING},
        reason="Catch import errors before execution",
        validator=_validate_imports,
    ),
    Rule(
        name="no_banned_tokens",
        enabled=True,
        severity=Severity.BLOCKING,
        tier_overrides={},
        reason="Security: block eval, exec, os.system",
        validator=_validate_no_banned_tokens,
    ),
    Rule(
        name="signature_required",
        enabled=True,
        severity=Severity.BLOCKING,
        tier_overrides={Tier.SANDBOX: Severity.WARNING},
        reason="Cryptographic lineage enforcement",
        validator=_validate_signature,
    ),
    Rule(
        name="max_complexity_delta",
        enabled=False,
        severity=Severity.WARNING,
        tier_overrides={},
        reason="Prevent complexity explosions",
        validator=_validate_complexity,
    ),
    Rule(
        name="test_coverage_maintained",
        enabled=False,
        severity=Severity.WARNING,
        tier_overrides={},
        reason="Ensure mutations don't reduce test coverage",
        validator=_validate_coverage,
    ),
    Rule(
        name="max_mutation_rate",
        enabled=False,
        severity=Severity.ADVISORY,
        tier_overrides={},
        reason="Prevent runaway mutation loops",
        validator=_validate_mutation_rate,
    ),
    Rule(
        name="lineage_continuity",
        enabled=False,
        severity=Severity.BLOCKING,
        tier_overrides={},
        reason="Every mutation must trace to certified ancestor",
        validator=_validate_lineage,
    ),
    Rule(
        name="resource_bounds",
        enabled=False,
        severity=Severity.BLOCKING,
        tier_overrides={},
        reason="Mutation cannot exceed memory/CPU/time budgets",
        validator=_validate_resources,
    ),
]


def get_rules_for_tier(tier: Tier) -> List[tuple[Rule, Severity]]:
    """Return enabled rules with tier-specific severity overrides applied."""
    result: List[tuple[Rule, Severity]] = []
    for rule in RULES:
        if not rule.enabled:
            continue
        severity = rule.tier_overrides.get(tier, rule.severity)
        result.append((rule, severity))
    return result


def evaluate_mutation(request: MutationRequest, tier: Tier) -> Dict[str, Any]:
    """
    Apply all constitutional rules to a mutation request.

    Returns:
        Verdict with detailed rule evaluations and blocking status.
    """
    rules = get_rules_for_tier(tier)
    verdicts: List[Dict[str, Any]] = []
    blocking_failures: List[str] = []
    warnings: List[str] = []

    for rule, severity in rules:
        try:
            result = rule.validator(request)
        except Exception as exc:
            result = {"ok": False, "reason": f"validator_error:{exc}"}

        verdict = {
            "rule": rule.name,
            "severity": severity.value,
            "passed": result.get("ok", False),
            "details": result,
        }
        verdicts.append(verdict)

        if not verdict["passed"]:
            if severity == Severity.BLOCKING:
                blocking_failures.append(rule.name)
            elif severity == Severity.WARNING:
                warnings.append(rule.name)

    passed = len(blocking_failures) == 0

    evaluation = {
        "constitution_version": CONSTITUTION_VERSION,
        "tier": tier.name,
        "tier_value": tier.value,
        "passed": passed,
        "verdicts": verdicts,
        "blocking_failures": blocking_failures,
        "warnings": warnings,
        "agent_id": request.agent_id,
        "intent": request.intent,
    }

    metrics.log(
        event_type="constitutional_evaluation",
        payload=evaluation,
        level="INFO" if passed else "ERROR",
        element_id=ELEMENT_ID,
    )

    return evaluation


def determine_tier(agent_id: str) -> Tier:
    """
    Determine trust tier based on agent path.

    Args:
        agent_id: Agent identifier (e.g., "test_subject" or "sample_agent")

    Returns:
        Appropriate tier for the agent.
    """
    forced = get_forced_tier()
    if forced is not None:
        return forced

    agent_id_lower = agent_id.lower()

    if "test_subject" in agent_id_lower or "sandbox" in agent_id_lower:
        return Tier.SANDBOX

    production_keywords = ["runtime", "security", "main", "orchestrator", "cryovant"]
    if any(keyword in agent_id_lower for keyword in production_keywords):
        return Tier.PRODUCTION

    return Tier.STABLE


def get_forced_tier() -> Tier | None:
    """
    Return the forced tier from ADAAD_FORCE_TIER, if configured.
    """
    value = os.getenv("ADAAD_FORCE_TIER")
    if not value:
        return None
    normalized = value.strip().upper()
    try:
        return Tier[normalized]
    except KeyError:
        return None


__all__ = [
    "evaluate_mutation",
    "determine_tier",
    "get_forced_tier",
    "Tier",
    "Severity",
    "CONSTITUTION_VERSION",
    "RULES",
]
