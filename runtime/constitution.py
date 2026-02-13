# SPDX-License-Identifier: Apache-2.0
"""
Constitutional rules governing ADAAD mutation safety.

The constitution is versioned, tiered, auditable, and evolvable.
Every mutation passes through constitutional evaluation before execution.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping

from app.agents.mutation_request import MutationRequest
from runtime import metrics
from runtime.metrics_analysis import mutation_rate_snapshot
from security.ledger import journal

CONSTITUTION_VERSION = "0.1.0"
ELEMENT_ID = "Earth"
POLICY_PATH = Path("runtime/governance/constitution.yaml")


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
    """Report mutation scope without blocking multi-file operations."""
    from runtime.preflight import _extract_targets

    targets = _extract_targets(request)
    return {
        "ok": True,
        "target_count": len(targets),
        "targets": [str(target) for target in targets],
    }


def _validate_ast(request: MutationRequest) -> Dict[str, Any]:
    """Validate Python AST parsability."""
    from runtime.preflight import _ast_check, _extract_source, _extract_targets

    targets = _extract_targets(request)
    if not targets:
        return {"ok": True, "reason": "no_targets"}

    checks: Dict[str, Any] = {}
    ok = True
    for target in targets:
        source = _extract_source(request, target)
        result = _ast_check(target, source)
        checks[str(target)] = result
        if not result.get("ok"):
            ok = False
    return {"ok": ok, "targets": checks}


def _validate_imports(request: MutationRequest) -> Dict[str, Any]:
    """Smoke test import validity."""
    from runtime.preflight import _extract_source, _extract_targets, _import_smoke_check

    targets = _extract_targets(request)
    if not targets:
        return {"ok": True, "reason": "no_targets"}

    checks: Dict[str, Any] = {}
    ok = True
    for target in targets:
        source = _extract_source(request, target)
        result = _import_smoke_check(target, source)
        checks[str(target)] = result
        if not result.get("ok"):
            ok = False
    return {"ok": ok, "targets": checks}


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

    findings: Dict[str, List[str]] = {}
    ok = True
    for target in targets:
        source = _extract_source(request, target)
        if not source:
            if target.exists():
                source = target.read_text(encoding="utf-8")
            else:
                continue
        found = [token for token in banned if token in source]
        if found:
            ok = False
            findings[str(target)] = found
    if not ok:
        return {"ok": False, "reason": "banned_tokens", "found": findings}
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
    """Check mutation rate limits against recent metrics."""
    max_rate_env = os.getenv("ADAAD_MAX_MUTATIONS_PER_HOUR", "60").strip()
    window_env = os.getenv("ADAAD_MUTATION_RATE_WINDOW_SEC", "3600").strip()
    try:
        max_rate = float(max_rate_env)
    except ValueError:
        return {"ok": False, "reason": "invalid_max_rate", "details": {"value": max_rate_env}}
    try:
        window_sec = int(window_env)
    except ValueError:
        return {"ok": False, "reason": "invalid_window_sec", "details": {"value": window_env}}
    if max_rate <= 0:
        return {
            "ok": True,
            "reason": "rate_limit_disabled",
            "details": {"max_mutations_per_hour": max_rate, "window_sec": window_sec},
        }
    snapshot = mutation_rate_snapshot(window_sec)
    exceeded = snapshot["rate_per_hour"] > max_rate
    return {
        "ok": not exceeded,
        "reason": "rate_limit_exceeded" if exceeded else "rate_limit_ok",
        "details": {
            "max_mutations_per_hour": max_rate,
            "window_sec": window_sec,
            "count": snapshot["count"],
            "rate_per_hour": snapshot["rate_per_hour"],
            "window_start_ts": snapshot["window_start_ts"],
            "window_end_ts": snapshot["window_end_ts"],
            "event_types": snapshot["event_types"],
        },
    }


def _validate_resources(_: MutationRequest) -> Dict[str, Any]:
    """Enforce resource bounds (stub for now)."""
    return {"ok": True, "reason": "not_yet_implemented"}


VALIDATOR_REGISTRY: Dict[str, Callable[[MutationRequest], Dict[str, Any]]] = {
    "single_file_scope": _validate_single_file,
    "ast_validity": _validate_ast,
    "import_smoke_test": _validate_imports,
    "signature_required": _validate_signature,
    "no_banned_tokens": _validate_no_banned_tokens,
    "lineage_continuity": _validate_lineage,
    "max_complexity_delta": _validate_complexity,
    "test_coverage_maintained": _validate_coverage,
    "max_mutation_rate": _validate_mutation_rate,
    "resource_bounds": _validate_resources,
}


def _policy_hash(policy_text: str) -> str:
    return hashlib.sha256(policy_text.encode("utf-8")).hexdigest()


def _load_policy_document(path: Path) -> tuple[Mapping[str, Any], str]:
    if not path.exists():
        raise ValueError(f"constitution_policy_missing:{path}")
    raw = path.read_text(encoding="utf-8")
    try:
        policy = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"constitution_policy_invalid_json:{exc}") from exc
    if not isinstance(policy, dict):
        raise ValueError("constitution_policy_invalid_schema:root_not_object")
    return policy, _policy_hash(raw)


def _validate_policy_schema(policy: Mapping[str, Any], expected_version: str) -> None:
    version = policy.get("version")
    if version != expected_version:
        raise ValueError(f"constitution_version_mismatch:{version}!={expected_version}")

    tiers = policy.get("tiers")
    if not isinstance(tiers, dict) or not tiers:
        raise ValueError("constitution_policy_invalid_schema:tiers")
    for tier in Tier:
        if tier.name not in tiers:
            raise ValueError(f"constitution_policy_invalid_schema:missing_tier:{tier.name}")
        if tiers[tier.name] != tier.value:
            raise ValueError(f"constitution_policy_invalid_schema:tier_value_mismatch:{tier.name}")

    severities = policy.get("severities")
    allowed = {severity.value for severity in Severity}
    if not isinstance(severities, list) or set(severities) != allowed:
        raise ValueError("constitution_policy_invalid_schema:severities")

    immutability = policy.get("immutability_constraints")
    if not isinstance(immutability, dict):
        raise ValueError("constitution_policy_invalid_schema:immutability_constraints")
    required_rule_keys = immutability.get("required_rule_keys")
    if not isinstance(required_rule_keys, list) or not required_rule_keys:
        raise ValueError("constitution_policy_invalid_schema:required_rule_keys")

    rules = policy.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("constitution_policy_invalid_schema:rules")
    for index, raw_rule in enumerate(rules):
        if not isinstance(raw_rule, dict):
            raise ValueError(f"constitution_policy_invalid_schema:rule_not_object:{index}")
        missing_keys = [key for key in required_rule_keys if key not in raw_rule]
        if missing_keys:
            raise ValueError(f"constitution_policy_invalid_schema:rule_missing_keys:{index}:{','.join(missing_keys)}")
        if raw_rule.get("severity") not in allowed:
            raise ValueError(f"constitution_policy_invalid_schema:rule_severity:{raw_rule.get('name', index)}")
        validator_name = raw_rule.get("validator")
        if validator_name not in VALIDATOR_REGISTRY:
            raise ValueError(f"constitution_policy_invalid_schema:validator:{validator_name}")
        overrides = raw_rule.get("tier_overrides")
        if not isinstance(overrides, dict):
            raise ValueError(f"constitution_policy_invalid_schema:tier_overrides:{raw_rule.get('name', index)}")
        for tier_name, severity_name in overrides.items():
            if tier_name not in tiers:
                raise ValueError(f"constitution_policy_invalid_schema:override_tier:{raw_rule.get('name', index)}:{tier_name}")
            if severity_name not in allowed:
                raise ValueError(
                    f"constitution_policy_invalid_schema:override_severity:{raw_rule.get('name', index)}:{severity_name}"
                )


def _record_amendment(old_hash: str | None, new_hash: str, version: str) -> None:
    if old_hash is None or old_hash == new_hash:
        return
    payload = {"version": version, "old_policy_hash": old_hash, "new_policy_hash": new_hash}
    journal.write_entry(agent_id="system", action="constitutional_amendment", payload=payload)
    journal.append_tx(tx_type="constitutional_amendment", payload=payload)


def load_constitution_policy(path: Path = POLICY_PATH, expected_version: str = CONSTITUTION_VERSION) -> tuple[List[Rule], str]:
    policy, policy_hash = _load_policy_document(path)
    _validate_policy_schema(policy, expected_version)

    rule_objects: List[Rule] = []
    for raw_rule in policy["rules"]:
        tier_overrides = {
            Tier[tier_name]: Severity(severity_name)
            for tier_name, severity_name in (raw_rule.get("tier_overrides") or {}).items()
        }
        rule_objects.append(
            Rule(
                name=str(raw_rule["name"]),
                enabled=bool(raw_rule["enabled"]),
                severity=Severity(str(raw_rule["severity"])),
                tier_overrides=tier_overrides,
                reason=str(raw_rule["reason"]),
                validator=VALIDATOR_REGISTRY[str(raw_rule["validator"])],
            )
        )
    return rule_objects, policy_hash


try:
    RULES, POLICY_HASH = load_constitution_policy()
except ValueError as exc:
    raise RuntimeError(f"constitution_boot_failed:{exc}") from exc

_record_amendment(old_hash=None, new_hash=POLICY_HASH, version=CONSTITUTION_VERSION)


def reload_constitution_policy(path: Path = POLICY_PATH) -> str:
    """Reload policy artifact and log hash delta as a constitutional amendment."""
    global RULES, POLICY_HASH
    old_hash = POLICY_HASH
    rules, new_hash = load_constitution_policy(path=path, expected_version=CONSTITUTION_VERSION)
    RULES = rules
    POLICY_HASH = new_hash
    _record_amendment(old_hash=old_hash, new_hash=new_hash, version=CONSTITUTION_VERSION)
    return new_hash


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
        "policy_hash": POLICY_HASH,
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
    "load_constitution_policy",
    "reload_constitution_policy",
    "Tier",
    "Severity",
    "CONSTITUTION_VERSION",
    "RULES",
    "POLICY_HASH",
    "POLICY_PATH",
]
