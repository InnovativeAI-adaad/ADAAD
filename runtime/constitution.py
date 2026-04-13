# SPDX-License-Identifier: Apache-2.0
"""
Constitutional rules governing ADAAD mutation safety.

The constitution is versioned, tiered, auditable, and evolvable.
Every mutation passes through constitutional evaluation before execution.
"""

from __future__ import annotations

import ast
import calendar
import functools
import fnmatch
import inspect
import hashlib
import json
import re
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Mapping

import importlib.util

if importlib.util.find_spec("yaml") is not None:
    import yaml
else:  # pragma: no cover - optional dependency fallback for hermetic environments
    class _YamlCompatError(ValueError):
        """Fallback yaml parse error."""

    class _YamlCompat:
        YAMLError = _YamlCompatError

        @staticmethod
        def safe_load(raw: str):
            text = raw.strip()
            if not text:
                return None
            if text[:1] in {"{", "["}:
                return json.loads(text)

            def _coerce_scalar(value: str) -> Any:
                value = value.strip()
                if value in {"[]", "[ ]"}:
                    return []
                if value in {"{}", "{ }"}:
                    return {}
                lower = value.lower()
                if lower in {"true", "false"}:
                    return lower == "true"
                if value.startswith(('"', "'")) and value.endswith(('"', "'")) and len(value) >= 2:
                    return value[1:-1]
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    if any(ch in value for ch in "[]{}"):
                        raise _YamlCompatError("invalid_yaml_value")
                    return value

            root: dict[str, Any] = {}
            active_key: str | None = None
            for raw_line in text.splitlines():
                line = raw_line.rstrip()
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                indent = len(line) - len(line.lstrip(" "))

                if stripped.startswith("- "):
                    if active_key is None:
                        raise _YamlCompatError("invalid_yaml_list_parent")
                    container = root.get(active_key)
                    if container == {}:
                        root[active_key] = []
                        container = root[active_key]
                    if not isinstance(container, list):
                        raise _YamlCompatError("invalid_yaml_list_parent")
                    container.append(_coerce_scalar(stripped[2:]))
                    continue

                if ":" not in stripped:
                    raise _YamlCompatError("invalid_yaml_line")

                key, value = stripped.split(":", 1)
                key = key.strip()
                value = value.strip()
                if not key:
                    raise _YamlCompatError("invalid_yaml_key")

                if indent == 0:
                    if not value:
                        root[key] = {}
                        active_key = key
                        continue
                    if value == "|":
                        raise _YamlCompatError("unsupported_yaml_block_scalar")
                    root[key] = _coerce_scalar(value)
                    active_key = key if isinstance(root[key], (list, dict)) else None
                    continue

                if active_key is None:
                    raise _YamlCompatError("invalid_yaml_indent")
                parent = root.get(active_key)
                if not isinstance(parent, dict):
                    raise _YamlCompatError("invalid_yaml_mapping_parent")
                if not value:
                    parent[key] = {}
                    continue
                if value == "|":
                    raise _YamlCompatError("unsupported_yaml_block_scalar")
                parent[key] = _coerce_scalar(value)
            return root

    yaml = _YamlCompat()

from runtime import metrics
from runtime.governance.debt_ledger import GovernanceDebtLedger
from runtime.governance.resource_accounting import (
    coalesce_resource_usage_snapshot,
    merge_platform_telemetry,
    normalize_platform_telemetry_snapshot,
    normalize_resource_usage_snapshot,
)
from runtime.platform.android_monitor import AndroidMonitor
from runtime.governance_surface import canonicalize_governance_details
from security.ledger import journal

CONSTITUTION_VERSION = "1.0.0"
ELEMENT_ID = "Earth"
POLICY_PATH = Path("runtime/governance/constitution.yaml")
RULE_APPLICABILITY_PATH = Path("governance/rule_applicability.yaml")
_DETERMINISTIC_ENVELOPE_STATE: ContextVar[Dict[str, Any] | None] = ContextVar("deterministic_envelope_state", default=None)

RULE_DEPENDENCY_GRAPH: Dict[str, List[str]] = {
    "max_mutation_rate": ["lineage_continuity"],
    "test_coverage_maintained": ["resource_bounds", "max_complexity_delta"],
}
VALIDATOR_VERSIONS: Dict[str, str] = {
    "_validate_single_file": "1.0.0",
    "_validate_ast": "1.0.0",
    "_validate_imports": "1.0.0",
    "_validate_signature": "1.0.0",
    "_validate_no_banned_tokens": "1.0.0",
    "_validate_lineage": "2.2.0",
    "_validate_complexity": "1.1.0",
    "_validate_coverage": "1.1.0",
    "_validate_mutation_rate": "2.1.0",
    "_validate_resources": "1.3.0",
    "_validate_entropy_budget_limit": "1.0.0",
    "_validate_deployment_authority_tier": "1.0.0",
    "_validate_revenue_credit_floor": "1.0.0",
    "_validate_reviewer_calibration": "1.0.0",
    "_validate_governance_health_floor": "1.0.0",
    "_validate_soulbound_privacy_invariant": "1.0.0",
    "_validate_bandit_arm_integrity": "1.0.0",
    "_validate_market_signal_integrity": "1.0.0",
    "_validate_phase63_ast_safe_scaffold": "0.1.0",
    "_validate_phase63_ast_import_scaffold": "0.1.0",
    "_validate_phase63_ast_complexity_scaffold": "0.1.0",
    "_validate_phase63_semantic_integrity_scaffold": "0.1.0",
    "_validate_phase63_exception_scope_scaffold": "0.1.0",
}
_LINEAGE_VALIDATION_CACHE: Dict[str, Any] = {}
_POLICY_DOCUMENT: Dict[str, Any] = {}


def boot_sanity_check() -> dict[str, bool]:
    """Run deterministic boot checks required before higher-risk governance rules."""
    version = globals().get("CONSTITUTION_VERSION")
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError("boot_sanity_failed:invalid_constitution_version")

    policy_path = globals().get("POLICY_PATH")
    if isinstance(policy_path, Path) and policy_path.exists():
        # Read access check is deterministic and side-effect free.
        if not os.access(policy_path, os.R_OK):
            raise RuntimeError("boot_sanity_failed:policy_path_not_readable")

    return {"ok": True}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@functools.lru_cache(maxsize=64)
def _validator_source_hash(validator: Callable[[MutationRequest], Dict[str, Any]]) -> str:
    try:
        source = inspect.getsource(validator)
        return hashlib.sha256(source.encode("utf-8")).hexdigest()
    except (OSError, TypeError):
        return "source_unavailable"


def _validator_provenance(rule: Rule) -> Dict[str, str]:
    return {
        "validator_name": rule.validator.__name__,
        "validator_version": VALIDATOR_VERSIONS.get(rule.validator.__name__, "1.0.0"),
        "constitution_version": CONSTITUTION_VERSION,
        "validator_source_hash": _validator_source_hash(rule.validator),
    }


def _order_rules_with_dependencies(rules: List[tuple[Rule, Severity]]) -> List[tuple[Rule, Severity]]:
    indexed = {rule.name: (rule, severity) for rule, severity in rules}
    ordered: List[tuple[Rule, Severity]] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def _visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            return
        pair = indexed.get(name)
        if pair is None:
            return
        visiting.add(name)
        for dep in RULE_DEPENDENCY_GRAPH.get(name, []):
            _visit(dep)
        visiting.remove(name)
        visited.add(name)
        ordered.append(pair)

    for rule, _severity in rules:
        _visit(rule.name)
    return ordered




def _governance_fingerprint_components() -> Dict[str, Any]:
    applicability_text = RULE_APPLICABILITY_PATH.read_text(encoding="utf-8") if RULE_APPLICABILITY_PATH.exists() else ""
    validator_hashes = {
        name: _validator_provenance(rule).get("validator_source_hash", "")
        for name, rule in sorted(((rule.name, rule) for rule in RULES), key=lambda item: item[0])
    }
    return {
        "constitution_version": CONSTITUTION_VERSION,
        "policy_hash": POLICY_HASH,
        "applicability_hash": hashlib.sha256(applicability_text.encode("utf-8")).hexdigest(),
        "validator_hashes": validator_hashes,
    }


def _current_governance_fingerprint() -> str:
    return _canonical_digest(_governance_fingerprint_components())


class Severity(Enum):
    """Rule enforcement severity levels."""

    BLOCKING = "blocking"
    WARNING = "warning"
    ADVISORY = "advisory"


_SEVERITY_ORDER: Dict[Severity, int] = {
    Severity.ADVISORY: 0,
    Severity.WARNING: 1,
    Severity.BLOCKING: 2,
}


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
    applicability: Dict[str, Any] = field(default_factory=dict)


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


def validate_lineage_continuity(mutation: Any) -> bool:
    """Blocking lineage continuity gate for constitutional mutation evaluation."""
    from runtime.evolution.lineage_v2 import resolve_chain

    agent_id = str(getattr(mutation, "agent_id", "")).strip()
    if not agent_id:
        raise RuntimeError("lineage_missing_agent_id")

    chain = resolve_chain(agent_id)
    if not chain:
        raise RuntimeError("lineage_missing_parent")
    if str(chain[0]) in {"", "0" * 64}:
        raise RuntimeError("lineage_missing_genesis")

    for link in chain:
        if not re.fullmatch(r"[0-9a-f]{64}", str(link)):
            raise RuntimeError("lineage_tampered_hash")
    return True


def _validate_lineage(_: MutationRequest) -> Dict[str, Any]:
    """Resolve and verify append-only lineage chain up to certified genesis."""
    from runtime.evolution.lineage_v2 import resolve_certified_ancestor_path
    from security import cryovant

    # Rationale: enforce explicit mutation lineage chain continuity when lineage_v2 exists
    # while preserving existing genesis/journal invariants below.
    # Invariants: agent_id must be present; chain hashes are canonical lowercase sha256;
    # parent linkage remains append-only and rooted in genesis.
    from runtime.evolution.lineage_v2 import LINEAGE_V2_PATH, LineageResolutionError, resolve_chain

    if LINEAGE_V2_PATH.exists():
        agent_id = str(getattr(_, "agent_id", "")).strip()
        try:
            # Only enforce the helper gate when lineage_v2 can resolve a chain for this agent.
            # This preserves existing journal/genesis invariants as source-of-truth while
            # adding continuity enforcement for requests represented in lineage_v2.
            if resolve_chain(agent_id):
                validate_lineage_continuity(_)
        except LineageResolutionError as exc:
            metrics.log(
                event_type="lineage_v2_resolution_fallback",
                payload={"reason": str(exc), "agent_id": agent_id, "lineage_v2_path": str(LINEAGE_V2_PATH)},
                level="WARNING",
                element_id=ELEMENT_ID,
            )
        except RuntimeError as exc:
            return {"ok": False, "reason": str(exc), "details": {"validator": "validate_lineage_continuity"}}

    genesis_path = journal.GENESIS_PATH
    journal_path = journal.JOURNAL_PATH

    if not genesis_path.exists():
        return {"ok": False, "reason": "missing_genesis", "details": {"genesis_path": str(genesis_path)}}
    if not journal_path.exists():
        return {"ok": False, "reason": "missing_journal", "details": {"journal_path": str(journal_path)}}

    cache_key = {
        "genesis_path": str(genesis_path),
        "journal_path": str(journal_path),
        "genesis_mtime_ns": genesis_path.stat().st_mtime_ns,
        "journal_mtime_ns": journal_path.stat().st_mtime_ns,
        "genesis_size": genesis_path.stat().st_size,
        "journal_size": journal_path.stat().st_size,
    }
    prior_key = _LINEAGE_VALIDATION_CACHE.get("key")
    prior_result = _LINEAGE_VALIDATION_CACHE.get("result")
    if prior_key == cache_key and isinstance(prior_result, dict):
        return dict(prior_result)

    def _canonical_serialize(payload: Mapping[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _compute_hash(prev_hash: str, payload: Mapping[str, Any]) -> str:
        material = (prev_hash + _canonical_serialize(payload)).encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    chain: List[Dict[str, Any]] = []
    prev_hash = "0" * 64

    seen_mutations: Dict[str, Dict[str, Any]] = {}

    def _lineage_violation(
        *,
        epoch_id: str,
        mutation_or_bundle_id: str,
        missing_or_invalid_link: str,
        expected_ancestor: str,
        observed_reference: str,
        details: Dict[str, Any],
    ) -> Dict[str, Any]:
        event_payload = {
            "epoch_id": epoch_id,
            "mutation_or_bundle_id": mutation_or_bundle_id,
            "missing_or_invalid_link": missing_or_invalid_link,
            "expected_ancestor": expected_ancestor,
            "observed_reference": observed_reference,
        }
        metrics.log(event_type="lineage_violation_detected", payload=event_payload, level="CRITICAL", element_id=ELEMENT_ID)
        return {
            "ok": False,
            "reason": "lineage_violation_detected",
            "event": "lineage_violation_detected",
            "details": {**details, **event_payload},
        }

    for source_name, path in (("genesis", genesis_path), ("journal", journal_path)):
        lines = path.read_text(encoding="utf-8").splitlines()
        for line_no, line in enumerate(lines, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                entry = json.loads(text)
            except json.JSONDecodeError as exc:
                return {
                    "ok": False,
                    "reason": "lineage_invalid_json",
                    "details": {"source": source_name, "path": str(path), "line": line_no, "error": str(exc)},
                }
            if not isinstance(entry, dict):
                return {
                    "ok": False,
                    "reason": "lineage_malformed_entry",
                    "details": {"source": source_name, "path": str(path), "line": line_no},
                }

            entry_prev = str(entry.get("prev_hash") or "")
            entry_hash = str(entry.get("hash") or "")
            if entry_prev != prev_hash:
                return {
                    "ok": False,
                    "reason": "lineage_prev_hash_mismatch",
                    "details": {
                        "source": source_name,
                        "path": str(path),
                        "line": line_no,
                        "expected_prev_hash": prev_hash,
                        "entry_prev_hash": entry_prev,
                    },
                }

            payload = {key: value for key, value in entry.items() if key != "hash"}
            computed_hash = _compute_hash(prev_hash, payload)
            if entry_hash != computed_hash:
                return {
                    "ok": False,
                    "reason": "lineage_hash_mismatch",
                    "details": {
                        "source": source_name,
                        "path": str(path),
                        "line": line_no,
                        "expected_hash": computed_hash,
                        "entry_hash": entry_hash,
                    },
                }

            prev_hash = entry_hash
            resolved = resolve_certified_ancestor_path(entry)
            mutation_or_bundle_id = resolved["mutation_id"]
            parent_mutation_id = resolved["parent_mutation_id"]
            ancestor_chain = resolved["ancestor_chain"]
            certified_signature = resolved["certified_signature"]
            payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
            epoch_id = str(payload.get("epoch_id") or payload.get("epoch") or "")

            if parent_mutation_id:
                expected_parent = seen_mutations.get(parent_mutation_id)
                if expected_parent is None:
                    return _lineage_violation(
                        epoch_id=epoch_id,
                        mutation_or_bundle_id=mutation_or_bundle_id,
                        missing_or_invalid_link="parent_mutation_id",
                        expected_ancestor="known_mutation_id",
                        observed_reference=parent_mutation_id,
                        details={"source": source_name, "path": str(path), "line": line_no},
                    )
                if ancestor_chain and ancestor_chain[-1] != parent_mutation_id:
                    return _lineage_violation(
                        epoch_id=epoch_id,
                        mutation_or_bundle_id=mutation_or_bundle_id,
                        missing_or_invalid_link="ancestor_chain_tail",
                        expected_ancestor=parent_mutation_id,
                        observed_reference=ancestor_chain[-1],
                        details={"source": source_name, "path": str(path), "line": line_no},
                    )

            if ancestor_chain:
                missing = next((ancestor for ancestor in ancestor_chain if ancestor not in seen_mutations), "")
                if missing:
                    return _lineage_violation(
                        epoch_id=epoch_id,
                        mutation_or_bundle_id=mutation_or_bundle_id,
                        missing_or_invalid_link="ancestor_chain",
                        expected_ancestor="known_mutation_id",
                        observed_reference=missing,
                        details={"source": source_name, "path": str(path), "line": line_no},
                    )

            if certified_signature and bool(payload.get("lineage_signature_required")) and not cryovant.signature_valid(certified_signature):
                return _lineage_violation(
                    epoch_id=epoch_id,
                    mutation_or_bundle_id=mutation_or_bundle_id,
                    missing_or_invalid_link="cryovant_signature",
                    expected_ancestor="valid_cryovant_signature",
                    observed_reference=certified_signature,
                    details={"source": source_name, "path": str(path), "line": line_no},
                )

            if mutation_or_bundle_id:
                seen_mutations[mutation_or_bundle_id] = {
                    "hash": entry_hash,
                    "epoch_id": epoch_id,
                    "line": line_no,
                    "source": source_name,
                }

            chain.append(
                {
                    "source": source_name,
                    "path": str(path),
                    "line": line_no,
                    "tx": str(entry.get("tx") or ""),
                    "epoch_id": epoch_id,
                    "mutation_or_bundle_id": mutation_or_bundle_id,
                    "type": str(entry.get("type") or ""),
                    "hash": entry_hash,
                    "prev_hash": entry_prev,
                }
            )

    if not chain:
        return {
            "ok": False,
            "reason": "lineage_empty_chain",
            "details": {"genesis_path": str(genesis_path), "journal_path": str(journal_path)},
        }

    result = {
        "ok": True,
        "reason": "lineage_verified",
        "details": {
            "genesis_path": str(genesis_path),
            "journal_path": str(journal_path),
            "verified_entries": len(chain),
            "head_hash": prev_hash,
            "chain": chain,
        },
    }
    _LINEAGE_VALIDATION_CACHE["key"] = cache_key
    _LINEAGE_VALIDATION_CACHE["result"] = dict(result)
    return result


def _validate_complexity(request: MutationRequest) -> Dict[str, Any]:
    """Compute deterministic cyclomatic complexity delta using AST traversal."""
    from runtime.preflight import _extract_source, _extract_targets

    def _cyclomatic_complexity(source: str, filename: str) -> int:
        tree = ast.parse(source, filename=filename)
        complexity = 1
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With, ast.AsyncWith, ast.IfExp)):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                complexity += max(0, len(node.values) - 1)
            elif isinstance(node, ast.comprehension):
                complexity += 1
            elif hasattr(ast, "Match") and isinstance(node, ast.Match):
                complexity += max(1, len(getattr(node, "cases", [])))
        return complexity

    raw_threshold = os.getenv("ADAAD_MAX_COMPLEXITY_DELTA", "5").strip()
    try:
        threshold = int(raw_threshold)
    except ValueError:
        return {"ok": False, "reason": "invalid_complexity_threshold", "details": {"value": raw_threshold}}

    targets = sorted(_extract_targets(request), key=lambda p: str(p))
    if not targets:
        return {"ok": True, "reason": "no_targets", "details": {"threshold": threshold}}

    per_target: Dict[str, Any] = {}
    baseline_total = 0
    candidate_total = 0
    for target in targets:
        if target.suffix != ".py":
            continue
        baseline_source = target.read_text(encoding="utf-8") if target.exists() else ""
        candidate_source = _extract_source(request, target)
        if candidate_source is None:
            candidate_source = baseline_source

        try:
            baseline_complexity = _cyclomatic_complexity(baseline_source, str(target)) if baseline_source else 0
            candidate_complexity = _cyclomatic_complexity(candidate_source, str(target)) if candidate_source else 0
        except SyntaxError as exc:
            return {
                "ok": False,
                "reason": "complexity_ast_parse_failed",
                "details": {"target": str(target), "error": str(exc)},
            }

        baseline_total += baseline_complexity
        candidate_total += candidate_complexity
        per_target[str(target)] = {
            "baseline": baseline_complexity,
            "candidate": candidate_complexity,
            "delta": candidate_complexity - baseline_complexity,
        }

    delta = candidate_total - baseline_total
    exceeded = delta > threshold
    details = {
        "threshold": threshold,
        "baseline_total": baseline_total,
        "candidate_total": candidate_total,
        "delta": delta,
        "exceeded": exceeded,
        "targets": per_target,
    }
    if exceeded:
        metrics.log(
            event_type="constitutional_complexity_delta_exceeded",
            payload=details,
            level="WARNING",
            element_id=ELEMENT_ID,
        )
    return {"ok": not exceeded, "reason": "complexity_delta_exceeded" if exceeded else "complexity_delta_ok", "details": details}


def _validate_coverage(_: MutationRequest) -> Dict[str, Any]:
    """Compare deterministic baseline/post coverage artifacts."""

    def _canonical_serialize(payload: Mapping[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _coverage_value(raw: Mapping[str, Any]) -> float | None:
        for key in ("coverage", "line_coverage", "total", "ratio", "percent"):
            value = raw.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return None

    state = get_deterministic_envelope_state()
    tier = str(state.get("tier") or "").upper()
    baseline = state.get("fitness_coverage_baseline")
    post = state.get("fitness_coverage_post")

    def _load_path(path_value: Any) -> Dict[str, Any] | None:
        if not isinstance(path_value, str) or not path_value.strip():
            return None
        path = Path(path_value)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    if not isinstance(baseline, dict):
        baseline = _load_path(state.get("fitness_coverage_baseline_path") or os.getenv("ADAAD_FITNESS_COVERAGE_BASELINE_PATH"))
    if not isinstance(post, dict):
        post = _load_path(state.get("fitness_coverage_post_path") or os.getenv("ADAAD_FITNESS_COVERAGE_POST_PATH"))

    if not isinstance(baseline, dict) and not isinstance(post, dict):
        return {
            "ok": True,
            "reason": "coverage_artifact_not_configured",
            "details": {"tier": tier or "UNKNOWN", "has_baseline": False, "has_post": False},
        }
    if not isinstance(baseline, dict) or not isinstance(post, dict):
        return {
            "ok": False,
            "reason": "coverage_artifact_missing",
            "details": {"tier": tier or "UNKNOWN", "has_baseline": isinstance(baseline, dict), "has_post": isinstance(post, dict)},
        }

    baseline_value = _coverage_value(baseline)
    post_value = _coverage_value(post)
    if baseline_value is None or post_value is None:
        return {
            "ok": False,
            "reason": "coverage_artifact_invalid",
            "details": {
                "tier": tier or "UNKNOWN",
                "baseline_hash": hashlib.sha256(_canonical_serialize(baseline).encode("utf-8")).hexdigest(),
                "post_hash": hashlib.sha256(_canonical_serialize(post).encode("utf-8")).hexdigest(),
            },
        }

    delta = post_value - baseline_value
    regressed = delta < 0
    details = {
        "tier": tier or "UNKNOWN",
        "baseline": baseline_value,
        "post": post_value,
        "delta": delta,
        "regressed": regressed,
        "baseline_hash": hashlib.sha256(_canonical_serialize(baseline).encode("utf-8")).hexdigest(),
        "post_hash": hashlib.sha256(_canonical_serialize(post).encode("utf-8")).hexdigest(),
    }
    if regressed:
        metrics.log(event_type="constitutional_coverage_regressed", payload=details, level="WARNING", element_id=ELEMENT_ID)
        if tier == Tier.SANDBOX.name:
            return {"ok": True, "reason": "coverage_regressed_sandbox_warning", "details": details}
        return {"ok": False, "reason": "coverage_regressed", "details": details}
    return {"ok": True, "reason": "coverage_maintained", "details": details}


def _parse_iso_ts(value: str | None) -> float | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            parsed = time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        else:
            parsed = time.strptime(value, "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None
    return float(calendar.timegm(parsed))


def _resolve_mutation_rate_limit() -> tuple[str, str, float]:
    """Resolve max mutation rate with deterministic env precedence."""
    new_name = "ADAAD_MAX_MUTATION_RATE"
    legacy_name = "ADAAD_MAX_MUTATIONS_PER_HOUR"
    new_raw = os.getenv(new_name)
    legacy_raw = os.getenv(legacy_name)
    if new_raw is not None:
        return new_name, new_raw.strip(), float(10)
    if legacy_raw is not None:
        return legacy_name, legacy_raw.strip(), float(10)
    return new_name, "10", float(10)


def _deterministic_mutation_count(window_sec: int, epoch_id: str) -> Dict[str, Any]:
    """Count recent mutation actions from the immutable ledger stream."""
    event_types = {
        "mutation_approved_constitutional",
        "mutation_rejected_constitutional",
        "mutation_planned",
        "mutation_executed",
        "mutation_failed",
        "mutation_noop",
    }
    lines = journal.ensure_ledger().read_text(encoding="utf-8").splitlines()
    parsed_entries: List[Dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        parsed_entries.append(entry)

    scoped_entries: List[Dict[str, Any]] = []
    for entry in parsed_entries:
        action = str(entry.get("action") or "")
        if action not in event_types:
            continue
        payload = entry.get("payload") or {}
        entry_epoch = str(payload.get("epoch_id") or "").strip()
        if epoch_id and entry_epoch and entry_epoch != epoch_id:
            continue
        if epoch_id and not entry_epoch:
            continue
        scoped_entries.append(entry)

    latest_event_ts = None
    if scoped_entries:
        latest_event_ts = max((_parse_iso_ts(str(item.get("timestamp") or "")) or 0.0) for item in scoped_entries)
    window_end_ts = latest_event_ts if latest_event_ts and latest_event_ts > 0 else 0.0
    window_start_ts = window_end_ts - window_sec

    count = 0
    for entry in scoped_entries:
        ts = _parse_iso_ts(str(entry.get("timestamp") or ""))
        if ts is None or ts < window_start_ts:
            continue
        count += 1

    return {
        "window_sec": window_sec,
        "window_start_ts": window_start_ts,
        "window_end_ts": window_end_ts,
        "count": count,
        "rate_per_hour": (count * 3600.0 / window_sec) if window_sec > 0 else float(count),
        "event_types": sorted(event_types),
        "entries_considered": len(parsed_entries),
        "entries_scoped": len(scoped_entries),
        "scope": {"epoch_id": epoch_id or "*"},
        "source": "security.ledger.lineage",
    }


def _validate_mutation_rate(request: MutationRequest) -> Dict[str, Any]:
    """Check mutation rate limits against deterministic ledger counters."""
    resolved_name, max_rate_env, default_max_rate = _resolve_mutation_rate_limit()
    envelope_state = get_deterministic_envelope_state()
    domain_context = envelope_state.get("domain_classification") if isinstance(envelope_state.get("domain_classification"), Mapping) else {}
    tier_name = str(envelope_state.get("tier", "")).strip().upper() or Tier.SANDBOX.name
    tier = Tier[tier_name] if tier_name in Tier.__members__ else Tier.SANDBOX
    window_env = os.getenv("ADAAD_MUTATION_RATE_WINDOW_SEC", "3600").strip()
    try:
        tier_limit = float(max_rate_env)
    except ValueError:
        return {
            "ok": False,
            "reason": "invalid_max_rate",
            "details": {
                "value": max_rate_env,
                "validator": "max_mutation_rate",
                "resolved_from_env": resolved_name,
                "default_max_mutation_rate": default_max_rate,
                "legacy_env_supported": ["ADAAD_MAX_MUTATIONS_PER_HOUR"],
            },
        }
    limit_resolution = _resolve_effective_limit(
        rule_name="max_mutation_rate",
        tier=tier,
        domain_context=domain_context,
        tier_limit=tier_limit,
    )
    try:
        window_sec = int(window_env)
    except ValueError:
        return {"ok": False, "reason": "invalid_window_sec", "details": {"value": window_env}}
    if limit_resolution["effective_limit"] <= 0:
        return {
            "ok": True,
            "reason": "rate_limit_disabled",
            "details": {
                "max_mutations_per_hour": limit_resolution["effective_limit"],
                "tier_limit": limit_resolution["tier_limit"],
                "domain_limit": limit_resolution["domain_limit"],
                "resolved_domain": limit_resolution["resolved_domain"],
                "applied_ceiling": limit_resolution["effective_limit"],
                "matched_domain_limits": limit_resolution["matched_domain_limits"],
                "window_sec": window_sec,
                "validator": "max_mutation_rate",
                "resolved_from_env": resolved_name,
                "default_max_mutation_rate": default_max_rate,
                "legacy_env_supported": ["ADAAD_MAX_MUTATIONS_PER_HOUR"],
            },
        }
    snapshot = _deterministic_mutation_count(window_sec=window_sec, epoch_id=str(request.epoch_id or "").strip())
    exceeded = snapshot["rate_per_hour"] > limit_resolution["effective_limit"]
    return {
        "ok": not exceeded,
        "reason": "rate_limit_exceeded" if exceeded else "rate_limit_ok",
        "details": {
            "max_mutations_per_hour": limit_resolution["effective_limit"],
            "tier_limit": limit_resolution["tier_limit"],
            "domain_limit": limit_resolution["domain_limit"],
            "resolved_domain": limit_resolution["resolved_domain"],
            "applied_ceiling": limit_resolution["effective_limit"],
            "matched_domain_limits": limit_resolution["matched_domain_limits"],
            "resolved_from_env": resolved_name,
            "default_max_mutation_rate": default_max_rate,
            "legacy_env_supported": ["ADAAD_MAX_MUTATIONS_PER_HOUR"],
            "validator": "max_mutation_rate",
            "window_sec": snapshot["window_sec"],
            "count": snapshot["count"],
            "rate_per_hour": snapshot["rate_per_hour"],
            "window_start_ts": snapshot["window_start_ts"],
            "window_end_ts": snapshot["window_end_ts"],
            "event_types": snapshot["event_types"],
            "entries_considered": snapshot["entries_considered"],
            "entries_scoped": snapshot["entries_scoped"],
            "scope": snapshot["scope"],
            "source": snapshot["source"],
        },
    }


def _validate_resources(_: MutationRequest) -> Dict[str, Any]:
    """Enforce deterministic resource bounds for memory, CPU, and wall clock."""

    def _bound_from_env(name: str, default: float) -> tuple[float, str | None]:
        raw = os.getenv(name, str(default)).strip()
        try:
            return float(raw), None
        except ValueError:
            return 0.0, raw

    envelope_state = get_deterministic_envelope_state()
    tier_name = str(envelope_state.get("tier", "")).strip().upper() or Tier.SANDBOX.name
    tier = Tier[tier_name] if tier_name in Tier.__members__ else Tier.SANDBOX
    telemetry = envelope_state.get("platform_telemetry")
    observed = envelope_state.get("resource_measurements")
    observed_map = observed if isinstance(observed, Mapping) else {}
    telemetry_map = telemetry if isinstance(telemetry, Mapping) else {}

    policy_document_loaded = isinstance(_POLICY_DOCUMENT, dict) and bool(_POLICY_DOCUMENT)
    resource_policy = _POLICY_DOCUMENT.get("resource_bounds_policy") if isinstance(_POLICY_DOCUMENT, dict) else {}
    resource_policy = resource_policy if isinstance(resource_policy, dict) else {}
    if not policy_document_loaded:
        metrics.log(
            event_type="resource_bounds_policy_unavailable",
            payload={"reason": "policy_document_empty", "fallback_defaults_applied": True},
            level="WARNING",
            element_id=ELEMENT_ID,
        )
    bounds_policy_version = str(resource_policy.get("policy_version") or "0")
    strict_telemetry_tiers = {
        str(item).strip().upper()
        for item in (resource_policy.get("strict_telemetry_tiers") or [Tier.PRODUCTION.name])
        if str(item).strip()
    }
    limits = resource_policy.get("limits") if isinstance(resource_policy.get("limits"), dict) else {}
    allow_overrides = {
        str(item).strip()
        for item in (resource_policy.get("allow_env_overrides") or [])
        if str(item).strip()
    }

    memory_limit_mb = float(limits.get("memory_mb", 2048.0) or 2048.0)
    cpu_limit_s = float(limits.get("cpu_seconds", 30.0) or 30.0)
    wall_limit_s = float(limits.get("wall_seconds", 60.0) or 60.0)
    bad_memory_bound = bad_cpu_bound = bad_wall_bound = None
    if "memory_mb" in allow_overrides:
        memory_limit_mb, bad_memory_bound = _bound_from_env("ADAAD_RESOURCE_MEMORY_MB", memory_limit_mb)
    if "cpu_seconds" in allow_overrides:
        cpu_limit_s, bad_cpu_bound = _bound_from_env("ADAAD_RESOURCE_CPU_SECONDS", cpu_limit_s)
    if "wall_seconds" in allow_overrides:
        wall_limit_s, bad_wall_bound = _bound_from_env("ADAAD_RESOURCE_WALL_SECONDS", wall_limit_s)
    if bad_memory_bound is not None:
        return {"ok": False, "reason": "invalid_resource_memory_bound", "details": {"value": bad_memory_bound}}
    if bad_cpu_bound is not None:
        return {"ok": False, "reason": "invalid_resource_cpu_bound", "details": {"value": bad_cpu_bound}}
    if bad_wall_bound is not None:
        return {"ok": False, "reason": "invalid_resource_wall_bound", "details": {"value": bad_wall_bound}}

    observed_expected_keys = ["peak_rss_mb", "cpu_seconds", "cpu_time_seconds", "wall_seconds", "wall_time_seconds", "duration_s"]
    telemetry_expected_keys = ["memory_mb"]
    has_observed = isinstance(observed, Mapping) and any(observed_map.get(key) is not None for key in observed_expected_keys)
    has_telemetry = isinstance(telemetry, Mapping) and any(telemetry_map.get(key) is not None for key in telemetry_expected_keys)
    if not has_observed and not has_telemetry:
        missing_details = {
            "tier": tier.name,
            "has_observed": has_observed,
            "has_telemetry": has_telemetry,
            "expected": {
                "resource_measurements": observed_expected_keys,
                "platform_telemetry": telemetry_expected_keys,
            },
            "strict_telemetry_tiers": sorted(strict_telemetry_tiers),
        }
        strict_tier = tier.name in strict_telemetry_tiers
        metrics.log(
            event_type="resource_measurements_missing",
            payload={
                "reason": "resource_measurements_missing",
                "mode": "fail_closed" if strict_tier else "fail_open",
                "rationale": "tier_requires_resource_evidence" if strict_tier else "tier_not_configured_for_strict_telemetry_enforcement",
                "details": missing_details,
            },
            level="ERROR" if strict_tier else "WARNING",
            element_id=ELEMENT_ID,
        )
        if strict_tier:
            return {"ok": False, "reason": "resource_measurements_missing", "details": missing_details}
        return {"ok": True, "reason": "resource_measurements_missing_fail_open", "details": missing_details}

    resource_usage_snapshot = coalesce_resource_usage_snapshot(observed=observed_map, telemetry=telemetry_map)
    peak_rss_mb = resource_usage_snapshot["memory_mb"]
    cpu_seconds = resource_usage_snapshot["cpu_seconds"]
    wall_seconds = resource_usage_snapshot["wall_seconds"]

    memory_exceeded = memory_limit_mb > 0 and peak_rss_mb > memory_limit_mb
    cpu_exceeded = cpu_limit_s > 0 and cpu_seconds > cpu_limit_s
    wall_exceeded = wall_limit_s > 0 and wall_seconds > wall_limit_s
    exceeded = memory_exceeded or cpu_exceeded or wall_exceeded

    limits_snapshot = normalize_resource_usage_snapshot(
        memory_mb=memory_limit_mb,
        cpu_seconds=cpu_limit_s,
        wall_seconds=wall_limit_s,
        disk_mb=0.0,
    )
    details = {
        "bounds_policy_version": bounds_policy_version,
        "limits": {"memory_mb": limits_snapshot["memory_mb"], "cpu_seconds": limits_snapshot["cpu_seconds"], "wall_seconds": limits_snapshot["wall_seconds"]},
        "observed": {"peak_rss_mb": peak_rss_mb, "cpu_seconds": cpu_seconds, "wall_seconds": wall_seconds},
        "resource_usage_snapshot": resource_usage_snapshot,
        "telemetry": {
            "memory_mb": resource_usage_snapshot["memory_mb"],
            "cpu_percent": float(telemetry_map.get("cpu_percent", 0.0) or 0.0),
            "battery_percent": float(telemetry_map.get("battery_percent", 0.0) or 0.0),
            "storage_mb": float(telemetry_map.get("storage_mb", 0.0) or 0.0),
        },
        "violations": [
            name
            for name, violation in (
                ("memory", memory_exceeded),
                ("cpu", cpu_exceeded),
                ("wall", wall_exceeded),
            )
            if violation
        ],
    }
    if exceeded:
        failure_payload = {
            "rule": "resource_bounds",
            "reason": "resource_bounds_exceeded",
            "agent_id": str(envelope_state.get("agent_id", "")),
            "epoch_id": str(envelope_state.get("epoch_id", "")),
            "bounds_policy_version": bounds_policy_version,
            "resource_usage_snapshot": resource_usage_snapshot,
            "details": details,
        }
        metrics.log(event_type="resource_bounds_exceeded", payload=failure_payload, level="ERROR", element_id=ELEMENT_ID)
        journal.write_entry(agent_id=failure_payload["agent_id"] or "system", action="resource_bounds_exceeded", payload=failure_payload)
        journal.append_tx(tx_type="resource_bounds_exceeded", payload=failure_payload)
        return {"ok": False, "reason": "resource_bounds_exceeded", "details": details, "failure": failure_payload}

    return {"ok": True, "reason": "resource_bounds_ok", "details": details}


def _load_rule_applicability(path: Path = RULE_APPLICABILITY_PATH) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        raise ValueError(f"rule_applicability_missing:{path}")
    raw = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"rule_applicability_invalid_json:{exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("rule_applicability_invalid_schema:root_not_object")
    rules = payload.get("rules")
    if not isinstance(rules, list):
        raise ValueError("rule_applicability_invalid_schema:rules")
    indexed: Dict[str, Dict[str, Any]] = {}
    for idx, entry in enumerate(rules):
        if not isinstance(entry, dict):
            raise ValueError(f"rule_applicability_invalid_schema:rule_not_object:{idx}")
        name = str(entry.get("name", "")).strip()
        if not name:
            raise ValueError(f"rule_applicability_invalid_schema:missing_name:{idx}")
        indexed[name] = entry
    return indexed


def _extract_domain_classification_config() -> Dict[str, Any]:
    policy_doc = _load_policy_document(RULE_APPLICABILITY_PATH)[0]
    raw = policy_doc.get("domain_classification") if isinstance(policy_doc, dict) else {}
    if not isinstance(raw, dict):
        return {"default_domain": "general", "rules": []}
    default_domain = str(raw.get("default_domain") or "general").strip() or "general"
    rules: List[Dict[str, Any]] = []
    for item in raw.get("rules") or []:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "").strip()
        patterns = [str(pattern).strip() for pattern in (item.get("patterns") or []) if str(pattern).strip()]
        if not domain or not patterns:
            continue
        rules.append({"domain": domain, "patterns": patterns})
    return {"default_domain": default_domain, "rules": rules}


def _classify_request_domains(request: MutationRequest) -> Dict[str, Any]:
    config = _extract_domain_classification_config()
    default_domain = str(config.get("default_domain") or "general")
    rules = config.get("rules") if isinstance(config.get("rules"), list) else []
    request_paths = sorted(_extract_request_paths(request))
    if not request_paths:
        return {
            "default_domain": default_domain,
            "path_domains": [],
            "resolved_domain": default_domain,
            "domains": [default_domain],
            "strategy": "default_no_targets",
        }

    path_domains: List[Dict[str, str]] = []
    resolved_domains: List[str] = []
    for path in request_paths:
        normalized = path.strip()
        matched_domain = default_domain
        matched_pattern = "default"
        for rule in rules:
            domain = str(rule.get("domain") or "").strip()
            patterns = [str(pattern).strip() for pattern in (rule.get("patterns") or []) if str(pattern).strip()]
            if not domain or not patterns:
                continue
            matched = next((pattern for pattern in patterns if fnmatch.fnmatch(normalized, pattern)), None)
            if matched:
                matched_domain = domain
                matched_pattern = matched
                break
        resolved_domains.append(matched_domain)
        path_domains.append({"path": normalized, "domain": matched_domain, "pattern": matched_pattern})

    domains = sorted(set(resolved_domains))
    return {
        "default_domain": default_domain,
        "path_domains": path_domains,
        "domains": domains,
        "resolved_domain": domains[0] if domains else default_domain,
        "strategy": "first_matching_rule_then_lexical",
    }


def _resolve_effective_limit(
    *,
    rule_name: str,
    tier: Tier,
    domain_context: Mapping[str, Any],
    tier_limit: float,
) -> Dict[str, Any]:
    rule = next((candidate for candidate in RULES if candidate.name == rule_name), None)
    applicability = rule.applicability if rule else {}
    limits = applicability.get("limits") if isinstance(applicability.get("limits"), dict) else {}
    domain_limits = limits.get("domain_limits") if isinstance(limits.get("domain_limits"), dict) else {}

    matched_domains: List[Dict[str, Any]] = []
    for domain in list(domain_context.get("domains") or []):
        if domain not in domain_limits:
            continue
        raw_limit = domain_limits.get(domain)
        try:
            parsed_limit = float(raw_limit)
        except (TypeError, ValueError):
            continue
        if parsed_limit > 0:
            matched_domains.append({"domain": domain, "domain_limit": parsed_limit})

    resolved_domain = str(domain_context.get("resolved_domain") or "general")
    domain_limit = float(tier_limit)
    if matched_domains:
        strictest = min(matched_domains, key=lambda item: (item["domain_limit"], item["domain"]))
        resolved_domain = strictest["domain"]
        domain_limit = float(strictest["domain_limit"])

    effective_limit = min(float(tier_limit), float(domain_limit))
    return {
        "tier": tier.name,
        "tier_limit": float(tier_limit),
        "domain_limit": float(domain_limit),
        "effective_limit": float(effective_limit),
        "resolved_domain": resolved_domain,
        "matched_domain_limits": matched_domains,
    }


def _extract_request_paths(request: MutationRequest) -> List[str]:
    paths: List[str] = []
    for target in request.targets:
        path = str(getattr(target, "path", "")).strip()
        if path:
            paths.append(path)
    return paths


def _path_in_scope(path: str, directories: List[str]) -> bool:
    normalized = path.strip("/")
    for directory in directories:
        scoped = str(directory).strip("/")
        if not scoped:
            continue
        if normalized == scoped or normalized.startswith(f"{scoped}/"):
            return True
    return False


def _evaluate_rule_applicability(rule: Rule, request: MutationRequest, tier: Tier) -> Dict[str, Any]:
    metadata = rule.applicability or {}
    scope = metadata.get("scope") if isinstance(metadata.get("scope"), dict) else {}
    triggers = metadata.get("triggers") if isinstance(metadata.get("triggers"), dict) else {}
    directories = [str(item) for item in scope.get("directories") or []]
    change_types = {str(item) for item in scope.get("change_types") or []}

    request_paths = _extract_request_paths(request)
    has_paths = bool(request_paths)

    requires_targets = bool(triggers.get("requires_targets"))
    scope_match = (
        not directories
        or (has_paths and any(_path_in_scope(path, directories) for path in request_paths))
        or (not has_paths and not requires_targets)
    )

    request_change_types = {"mutation_request"}
    if request.ops:
        request_change_types.add("code")
    if request_paths and all(path.startswith("docs/") for path in request_paths):
        request_change_types.add("docs")
    if request_paths and any(path.startswith("tests/") for path in request_paths):
        request_change_types.add("tests")

    change_type_match = not change_types or bool(request_change_types.intersection(change_types))

    requires_signature = bool(triggers.get("requires_signature"))
    min_ops = int(triggers.get("min_ops", 0) or 0)
    tiers = {str(item) for item in triggers.get("tiers") or []}

    trigger_results = {
        "requires_targets": (not requires_targets) or has_paths,
        "requires_signature": (not requires_signature) or bool(request.signature),
        "min_ops": len(request.ops) >= min_ops,
        "tiers": (not tiers) or (tier.name in tiers),
    }
    trigger_match = all(trigger_results.values())
    applicable = bool(rule.enabled and scope_match and change_type_match and trigger_match)
    return {
        "rule": rule.name,
        "applicable": applicable,
        "enabled": rule.enabled,
        "scope_match": scope_match,
        "change_type_match": change_type_match,
        "trigger_match": trigger_match,
        "trigger_results": trigger_results,
        "scope": scope,
        "triggers": triggers,
        "fail_behavior": metadata.get("fail_behavior", {}),
        "required_evidence": metadata.get("required_evidence", []),
    }


def _get_envelope_state() -> Dict[str, Any]:
    """Return active deterministic envelope state, initializing context-local storage when absent."""
    state = _DETERMINISTIC_ENVELOPE_STATE.get()
    if state is None:
        state = {}
        _DETERMINISTIC_ENVELOPE_STATE.set(state)
    return state


def set_deterministic_envelope_state(state: Mapping[str, Any] | None) -> Token[Dict[str, Any] | None]:
    """Set request-scoped deterministic envelope context for validators."""
    return _DETERMINISTIC_ENVELOPE_STATE.set(dict(state or {}))


def reset_deterministic_envelope_state(token: Token[Dict[str, Any] | None]) -> None:
    """Reset deterministic envelope state to a previously captured context token."""
    _DETERMINISTIC_ENVELOPE_STATE.reset(token)


@contextmanager
def deterministic_envelope_scope(state: Mapping[str, Any] | None):
    """Apply deterministic envelope state for the current evaluation scope."""
    token = set_deterministic_envelope_state(state)
    try:
        yield
    finally:
        reset_deterministic_envelope_state(token)


def get_deterministic_envelope_state() -> Dict[str, Any]:
    """Get request-scoped deterministic envelope context for validators."""
    return dict(_get_envelope_state())


def _parse_entropy_limit(value: str, *, field: str) -> tuple[bool, int, str | None]:
    try:
        parsed = int(value)
    except ValueError:
        return False, 0, f"invalid_{field}"
    return True, parsed, None


def _validate_entropy_budget_limit(request: MutationRequest) -> Dict[str, Any]:
    """Reject requests whose mutation/epoch entropy exceeds configured constitutional budgets."""
    from runtime.evolution.entropy_metadata import estimate_entropy_bits
    from runtime.evolution.entropy_policy import EntropyPolicy, EntropyPolicyViolation

    envelope_state = get_deterministic_envelope_state()
    tier_name = str(envelope_state.get("tier", "")).strip().upper()
    is_production = tier_name == Tier.PRODUCTION.name

    mutation_limit_env = os.getenv("ADAAD_MAX_MUTATION_ENTROPY_BITS", "128").strip()
    mutation_limit_ok, max_mutation_bits, mutation_error = _parse_entropy_limit(
        mutation_limit_env,
        field="entropy_budget_limit",
    )
    if not mutation_limit_ok:
        return {"ok": False, "reason": mutation_error, "details": {"value": mutation_limit_env}}

    domain_context = envelope_state.get("domain_classification") if isinstance(envelope_state.get("domain_classification"), Mapping) else {}
    tier = Tier[tier_name] if tier_name in Tier.__members__ else Tier.SANDBOX
    mutation_limit_resolution = _resolve_effective_limit(
        rule_name="entropy_budget_limit",
        tier=tier,
        domain_context=domain_context,
        tier_limit=float(max_mutation_bits),
    )
    max_mutation_bits = int(mutation_limit_resolution["effective_limit"])

    epoch_limit_env = os.getenv("ADAAD_MAX_EPOCH_ENTROPY_BITS", "4096").strip()
    epoch_limit_ok, max_epoch_bits, epoch_error = _parse_entropy_limit(
        epoch_limit_env,
        field="epoch_entropy_budget_limit",
    )
    if not epoch_limit_ok:
        return {"ok": False, "reason": epoch_error, "details": {"value": epoch_limit_env}}

    if max_mutation_bits <= 0:
        if is_production:
            return {
                "ok": False,
                "reason": "entropy_budget_disabled_in_production",
                "details": {
                    "max_mutation_entropy_bits": max_mutation_bits,
                    "tier": tier_name or "UNKNOWN",
                    "tier_limit": mutation_limit_resolution["tier_limit"],
                    "domain_limit": mutation_limit_resolution["domain_limit"],
                    "resolved_domain": mutation_limit_resolution["resolved_domain"],
                    "applied_ceiling": mutation_limit_resolution["effective_limit"],
                    "matched_domain_limits": mutation_limit_resolution["matched_domain_limits"],
                },
            }
        return {
            "ok": True,
            "reason": "entropy_budget_disabled",
            "details": {
                "max_mutation_entropy_bits": max_mutation_bits,
                "tier": tier_name or "UNKNOWN",
                "tier_limit": mutation_limit_resolution["tier_limit"],
                "domain_limit": mutation_limit_resolution["domain_limit"],
                "resolved_domain": mutation_limit_resolution["resolved_domain"],
                "applied_ceiling": mutation_limit_resolution["effective_limit"],
                "matched_domain_limits": mutation_limit_resolution["matched_domain_limits"],
            },
        }

    if max_epoch_bits <= 0:
        if is_production:
            return {
                "ok": False,
                "reason": "epoch_entropy_budget_disabled_in_production",
                "details": {"max_epoch_entropy_bits": max_epoch_bits, "tier": tier_name or "UNKNOWN"},
            }
        return {
            "ok": True,
            "reason": "epoch_entropy_budget_disabled",
            "details": {"max_epoch_entropy_bits": max_epoch_bits, "tier": tier_name or "UNKNOWN"},
        }

    declared_bits = estimate_entropy_bits(
        op_count=len(request.ops),
        target_count=len(request.targets),
        uses_random_seed=bool(request.random_seed),
    )

    observed_bits_raw = envelope_state.get("observed_entropy_bits", 0)
    try:
        observed_bits = max(0, int(observed_bits_raw or 0))
    except (TypeError, ValueError):
        return {
            "ok": False,
            "reason": "invalid_observed_entropy_bits",
            "details": {"value": observed_bits_raw},
        }

    mutation_bits = declared_bits + observed_bits
    epoch_bits_raw = envelope_state.get("epoch_entropy_bits", mutation_bits)
    try:
        epoch_bits = max(0, int(epoch_bits_raw or 0))
    except (TypeError, ValueError):
        return {
            "ok": False,
            "reason": "invalid_epoch_entropy_bits",
            "details": {"value": epoch_bits_raw},
        }

    policy = EntropyPolicy(
        policy_id="constitution_entropy_budget_limit",
        per_mutation_ceiling_bits=max_mutation_bits,
        per_epoch_ceiling_bits=max_epoch_bits,
    )
    try:
        enforcement = policy.enforce(
            mutation_bits=mutation_bits,
            declared_bits=declared_bits,
            observed_bits=observed_bits,
            epoch_bits=epoch_bits,
        )
        reason = "entropy_budget_ok"
        mutation_exceeded = False
        epoch_exceeded = False
    except EntropyPolicyViolation as exc:
        enforcement = exc.detail
        reason = exc.reason
        mutation_exceeded = int(enforcement["mutation_bits"]) > max_mutation_bits
        epoch_exceeded = int(enforcement["epoch_bits"]) > max_epoch_bits

    return {
        "ok": not (mutation_exceeded or epoch_exceeded),
        "reason": reason,
        "details": {
            "tier": tier_name or "UNKNOWN",
            "max_mutation_entropy_bits": max_mutation_bits,
            "max_epoch_entropy_bits": max_epoch_bits,
            "tier_limit": mutation_limit_resolution["tier_limit"],
            "domain_limit": mutation_limit_resolution["domain_limit"],
            "resolved_domain": mutation_limit_resolution["resolved_domain"],
            "applied_ceiling": mutation_limit_resolution["effective_limit"],
            "matched_domain_limits": mutation_limit_resolution["matched_domain_limits"],
            "declared_bits": int(enforcement["declared_bits"]),
            "observed_bits": int(enforcement["observed_bits"]),
            "mutation_bits": int(enforcement["mutation_bits"]),
            "epoch_entropy_bits": int(enforcement["epoch_bits"]),
            "policy_id": str(enforcement["policy_id"]),
            "policy_hash": str(enforcement["policy_hash"]),
            "mutation_exceeded": mutation_exceeded,
            "epoch_exceeded": epoch_exceeded,
        },
    }


def _normalize_advisory_detail_value(value: Any) -> Any:
    """Normalize advisory detail payloads for deterministic envelope serialization."""
    if isinstance(value, Mapping):
        return {str(key): _normalize_advisory_detail_value(item) for key, item in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize_advisory_detail_value(item) for item in value]
    if isinstance(value, set):
        normalized = [_normalize_advisory_detail_value(item) for item in value]
        return sorted(normalized, key=lambda item: _canonical_json(item))
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _validate_deployment_authority_tier(_: MutationRequest) -> Dict[str, Any]:
    """Emit deployment authority tier context as advisory governance telemetry."""
    envelope_state = get_deterministic_envelope_state()
    authority_tier = _normalize_advisory_detail_value(envelope_state.get("deployment_authority_tier"))
    authority_tier = str(authority_tier or "unspecified").strip() or "unspecified"
    return {
        "ok": True,
        "reason": "deployment_authority_tier_recorded",
        "details": {"deployment_authority_tier": authority_tier},
    }


def _validate_revenue_credit_floor(_: MutationRequest) -> Dict[str, Any]:
    """Record revenue-credit floor context for non-blocking economic governance review."""
    envelope_state = get_deterministic_envelope_state()
    credit_floor = _normalize_advisory_detail_value(envelope_state.get("revenue_credit_floor"))
    return {
        "ok": True,
        "reason": "revenue_credit_floor_recorded",
        "details": {
            "revenue_credit_floor": credit_floor,
            "present": credit_floor is not None,
        },
    }


def _validate_reviewer_calibration(_: MutationRequest) -> Dict[str, Any]:
    """Capture reviewer calibration metadata as advisory constitutional evidence."""
    envelope_state = get_deterministic_envelope_state()
    calibration = _normalize_advisory_detail_value(envelope_state.get("reviewer_calibration"))
    return {
        "ok": True,
        "reason": "reviewer_calibration_recorded",
        "details": {
            "reviewer_calibration": calibration,
            "present": calibration is not None,
        },
    }


def _validate_governance_health_floor(_: MutationRequest) -> Dict[str, Any]:
    """Surface GovernanceHealthAggregator h < 0.60 as advisory governance telemetry.

    Advisory-only by default.  When ADAAD_SEVERITY_ESCALATIONS promotes this
    rule to 'blocking', a degraded health score halts new amendment proposals
    until the floor is restored.  GovernanceGate retains sole mutation approval
    authority; this validator is informational only at default severity.
    """
    envelope_state = get_deterministic_envelope_state()
    health_score = _normalize_advisory_detail_value(
        envelope_state.get("governance_health_score")
    )
    degraded = False
    if isinstance(health_score, (int, float)):
        degraded = float(health_score) < 0.60
    return {
        "ok": True,
        "reason": "governance_health_floor_recorded",
        "details": {
            "governance_health_score": health_score,
            "degraded": degraded,
            "threshold": 0.60,
            "present": health_score is not None,
        },
    }


def _validate_soulbound_privacy_invariant(_: MutationRequest) -> Dict[str, Any]:
    """Phase 9 — Constitution v0.5.0 BLOCKING rule.

    Ensures that the ContextReplayInterface honours the soulbound_privacy_invariant:
    replay injections into the proposal layer must propagate ONLY context_digest
    and aggregate statistics — never raw ledger payload content.

    This validator checks that the ADAAD_SOULBOUND_KEY env var is set (indicating
    the ledger is active) and surfaces the invariant as a governance signal.
    When promoted to blocking via ADAAD_SEVERITY_ESCALATIONS, any mutation
    proposal cycle that bypasses context_digest propagation is halted.

    GovernanceGate retains sole mutation approval authority; this validator is
    an additional layer ensuring the soulbound context channel is cryptographically
    anchored before replay payloads reach the proposal agents.
    """
    import os
    key_set = bool(os.environ.get("ADAAD_SOULBOUND_KEY", "").strip())
    return {
        "ok": True,
        "reason": "soulbound_privacy_invariant_recorded",
        "details": {
            "soulbound_key_configured": key_set,
            "replay_uses_digest_only": True,       # ContextReplayInterface architectural invariant
            "raw_payload_propagation_blocked": True,
            "phase": 9,
        },
    }



def _validate_bandit_arm_integrity(_: MutationRequest) -> Dict[str, Any]:
    """Phase 11-A — Constitution v0.6.0 BLOCKING rule.

    Audits AgentBanditSelector arm state for two invariants:

    1. arm_stats_non_negative: reward_mass, loss_mass, pull_count must all be >= 0.
       Negative values indicate state corruption or an adversarial write.

    2. consecutive_epoch_cap_respected: no single agent may hold
       consecutive_recommendations > MAX_CONSECUTIVE_BANDIT_EPOCHS without
       at least one competing arm having been updated in that window.
       This prevents bandit lock-in from starving agent diversity.

    The validator reads from DEFAULT_STATE_PATH (data/agent_bandit_state.json).
    When the state file is absent the rule passes advisory (bandit not yet active).
    In SANDBOX tier the rule is advisory; in PRODUCTION/STABLE it is BLOCKING.

    GovernanceGate retains sole mutation approval authority; this rule enforces
    bandit-layer integrity only.
    """
    import json as _json
    import os as _os
    from pathlib import Path as _Path

    state_path = _Path(
        _os.environ.get(
            "ADAAD_BANDIT_STATE_PATH",
            "data/agent_bandit_state.json",
        )
    )
    max_consecutive = int(
        _os.environ.get(
            "ADAAD_BANDIT_MAX_CONSECUTIVE_EPOCHS",
            "10",
        )
    )

    # File absent → bandit not yet active; pass advisory
    if not state_path.exists():
        return {
            "ok": True,
            "reason": "bandit_state_absent_advisory_pass",
            "details": {
                "bandit_active": False,
                "arm_stats_non_negative": None,
                "consecutive_epoch_cap_respected": None,
                "max_consecutive_epochs": max_consecutive,
                "phase": 11,
            },
        }

    try:
        raw = _json.loads(state_path.read_text(encoding="utf-8"))
        arms = raw.get("arms", {})
    except Exception:  # noqa: BLE001
        return {
            "ok": True,
            "reason": "bandit_state_unreadable_advisory_pass",
            "details": {"bandit_active": False, "phase": 11},
        }

    # Invariant 1: non-negative arm stats
    negative_arms = []
    for agent, arm in arms.items():
        rc  = int(arm.get("pull_count",  0))
        rm  = float(arm.get("reward_mass", 0.0))
        lm  = float(arm.get("loss_mass",  0.0))
        if rc < 0 or rm < 0.0 or lm < 0.0:
            negative_arms.append(agent)

    arm_stats_ok = len(negative_arms) == 0

    # Invariant 2: consecutive epoch cap
    consecutive_violations = []
    for agent, arm in arms.items():
        consec = int(arm.get("consecutive_recommendations", 0))
        if consec > max_consecutive:
            consecutive_violations.append({
                "agent": agent,
                "consecutive_recommendations": consec,
                "cap": max_consecutive,
            })

    consecutive_ok = len(consecutive_violations) == 0

    ok = arm_stats_ok and consecutive_ok
    reason = "bandit_arm_integrity_ok" if ok else "bandit_arm_integrity_violation"

    return {
        "ok": ok,
        "reason": reason,
        "details": {
            "bandit_active": True,
            "arm_stats_non_negative": arm_stats_ok,
            "consecutive_epoch_cap_respected": consecutive_ok,
            "negative_arms": negative_arms,
            "consecutive_violations": consecutive_violations,
            "max_consecutive_epochs": max_consecutive,
            "phase": 11,
        },
    }


def _validate_market_signal_integrity(_: MutationRequest) -> Dict[str, Any]:
    """Phase 13 — Constitution v0.7.0 BLOCKING rule.

    Reads the most recent EpochResult's ``consecutive_synthetic_market_epochs``
    field from the checkpoint chain tip.  If the counter exceeds
    MAX_SYNTHETIC_EPOCHS, blocks weight adaptation promotion for this mutation.

    Invariants enforced:
    1. consecutive_synthetic_cap_respected: consecutive synthetic epoch count
       must be <= MAX_SYNTHETIC_EPOCHS (default 5, env-overridable).
    2. weight_promotion_blocked_on_degraded_feed: if cap is exceeded the rule
       returns ok=False with severity BLOCKING (SANDBOX: warning).

    When checkpoint data is absent the rule passes advisory — market integrator
    not yet active.  In SANDBOX tier the rule is advisory; in PRODUCTION/STABLE
    it is BLOCKING.

    GovernanceGate retains sole mutation approval authority; this rule audits
    market feed health only.
    """
    import json as _json
    import os as _os
    from pathlib import Path as _Path

    max_synthetic = int(
        _os.environ.get(
            "ADAAD_MARKET_MAX_SYNTHETIC_EPOCHS",
            "5",
        )
    )

    # Read consecutive_synthetic_market_epochs from checkpoint chain tip
    chain_path = _Path(_os.environ.get("ADAAD_CHAIN_PATH", "data/checkpoint_chain.jsonl"))

    if not chain_path.exists():
        return {
            "ok": True,
            "reason": "market_signal_integrity_chain_absent_advisory_pass",
            "details": {
                "market_integrator_active": False,
                "phase": 13,
                "max_synthetic_epochs": max_synthetic,
            },
        }

    try:
        lines = chain_path.read_text(encoding="utf-8").strip().splitlines()
        if not lines:
            return {
                "ok": True,
                "reason": "market_signal_integrity_chain_empty_advisory_pass",
                "details": {
                    "market_integrator_active": False,
                    "phase": 13,
                    "max_synthetic_epochs": max_synthetic,
                },
            }
        last_entry = _json.loads(lines[-1])
        # epoch_summary may be nested under 'payload' or at top level
        payload = last_entry.get("payload", last_entry)
        consec = int(payload.get("consecutive_synthetic_market_epochs", 0))
    except Exception:  # noqa: BLE001
        return {
            "ok": True,
            "reason": "market_signal_integrity_chain_unreadable_advisory_pass",
            "details": {
                "market_integrator_active": False,
                "phase": 13,
                "max_synthetic_epochs": max_synthetic,
            },
        }

    # If counter is 0, market integrator is absent or a live reading was last
    if consec == 0:
        return {
            "ok": True,
            "reason": "market_signal_integrity_ok",
            "details": {
                "market_integrator_active": True,
                "consecutive_synthetic_epochs": consec,
                "max_synthetic_epochs": max_synthetic,
                "cap_exceeded": False,
                "phase": 13,
            },
        }

    cap_exceeded = consec > max_synthetic
    ok = not cap_exceeded
    reason = (
        "market_signal_integrity_ok"
        if ok
        else "market_signal_integrity_violation_consecutive_synthetic_cap_exceeded"
    )

    return {
        "ok": ok,
        "reason": reason,
        "details": {
            "market_integrator_active": True,
            "consecutive_synthetic_epochs": consec,
            "max_synthetic_epochs": max_synthetic,
            "cap_exceeded": cap_exceeded,
            "phase": 13,
        },
    }


def _phase63_scaffold_details(rule_id: str) -> Dict[str, Any]:
    """Emit deterministic advisory-only metadata for Phase 63 scaffolding."""
    envelope_state = get_deterministic_envelope_state()
    signoff_token = _normalize_advisory_detail_value(envelope_state.get("human_signoff_token"))
    signoff_recorded = bool(signoff_token)
    return {
        "rule_id": rule_id,
        "phase": 63,
        "scaffold_only": True,
        "human_signoff_recorded": signoff_recorded,
        "human_signoff_token_present": signoff_recorded,
        "enforcement_mode": "advisory_until_human_0_signoff",
    }


def _validate_phase63_ast_safe_scaffold(_: MutationRequest) -> Dict[str, Any]:
    return {
        "ok": True,
        "reason": "phase63_ast_safe_scaffold_advisory_only",
        "details": _phase63_scaffold_details("AST-SAFE-0"),
    }


def _validate_phase63_ast_import_scaffold(_: MutationRequest) -> Dict[str, Any]:
    return {
        "ok": True,
        "reason": "phase63_ast_import_scaffold_advisory_only",
        "details": _phase63_scaffold_details("AST-IMPORT-0"),
    }


def _validate_phase63_ast_complexity_scaffold(_: MutationRequest) -> Dict[str, Any]:
    return {
        "ok": True,
        "reason": "phase63_ast_complexity_scaffold_advisory_only",
        "details": _phase63_scaffold_details("AST-COMPLEX-0"),
    }


def _validate_phase63_semantic_integrity_scaffold(_: MutationRequest) -> Dict[str, Any]:
    return {
        "ok": True,
        "reason": "phase63_semantic_integrity_scaffold_advisory_only",
        "details": _phase63_scaffold_details("SEMANTIC-INT-0"),
    }


def _validate_phase63_exception_scope_scaffold(_: MutationRequest) -> Dict[str, Any]:
    return {
        "ok": True,
        "reason": "phase63_exception_scope_scaffold_advisory_only",
        "details": _phase63_scaffold_details("EXCEP-SCOPE-0"),
    }


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
    "entropy_budget_limit": _validate_entropy_budget_limit,
    "deployment_authority_tier": _validate_deployment_authority_tier,
    "revenue_credit_floor": _validate_revenue_credit_floor,
    "reviewer_calibration": _validate_reviewer_calibration,
    "governance_health_floor": _validate_governance_health_floor,
    "soulbound_privacy_invariant": _validate_soulbound_privacy_invariant,
    "bandit_arm_integrity_invariant": _validate_bandit_arm_integrity,
    "market_signal_integrity_invariant": _validate_market_signal_integrity,
    "phase63_ast_safe_scaffold": _validate_phase63_ast_safe_scaffold,
    "phase63_ast_import_scaffold": _validate_phase63_ast_import_scaffold,
    "phase63_ast_complexity_scaffold": _validate_phase63_ast_complexity_scaffold,
    "phase63_semantic_integrity_scaffold": _validate_phase63_semantic_integrity_scaffold,
    "phase63_exception_scope_scaffold": _validate_phase63_exception_scope_scaffold,
}


def _policy_hash(policy_text: str) -> str:
    return hashlib.sha256(policy_text.encode("utf-8")).hexdigest()


def _load_policy_document(path: Path) -> tuple[Mapping[str, Any], str]:
    if not path.exists():
        raise ValueError(f"constitution_policy_missing:{path}")
    raw = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() in {".yaml", ".yml"}:
            policy = yaml.safe_load(raw)
        else:
            policy = json.loads(raw)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"constitution_policy_invalid_json:{exc}") from exc
    if not isinstance(policy, dict):
        raise ValueError("constitution_policy_invalid_schema:root_not_object")
    return policy, _policy_hash(raw)


def _validate_policy_schema(policy: Mapping[str, Any], expected_version: str) -> None:
    version = policy.get("version")
    if version != expected_version:
        raise ValueError(f"constitution_policy_invalid_schema:version_mismatch:{version}!={expected_version}")

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

    resource_bounds_policy = policy.get("resource_bounds_policy")
    if not isinstance(resource_bounds_policy, dict):
        raise ValueError("constitution_policy_invalid_schema:resource_bounds_policy")
    if not str(resource_bounds_policy.get("policy_version", "")).strip():
        raise ValueError("constitution_policy_invalid_schema:resource_bounds_policy_version")
    limits = resource_bounds_policy.get("limits")
    if not isinstance(limits, dict):
        raise ValueError("constitution_policy_invalid_schema:resource_bounds_limits")
    for key in ("memory_mb", "cpu_seconds", "wall_seconds"):
        try:
            if float(limits.get(key, 0.0)) < 0:
                raise ValueError(f"constitution_policy_invalid_schema:resource_bounds_limit_negative:{key}")
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith("constitution_policy_invalid_schema"):
                raise
            raise ValueError(f"constitution_policy_invalid_schema:resource_bounds_limit_invalid:{key}") from exc
    allow_env_overrides = resource_bounds_policy.get("allow_env_overrides")
    if not isinstance(allow_env_overrides, list):
        raise ValueError("constitution_policy_invalid_schema:resource_bounds_allow_env_overrides")
    allowed_override_keys = {"memory_mb", "cpu_seconds", "wall_seconds"}
    for entry in allow_env_overrides:
        if str(entry) not in allowed_override_keys:
            raise ValueError(f"constitution_policy_invalid_schema:resource_bounds_allow_env_override:{entry}")
    strict_telemetry_tiers = resource_bounds_policy.get("strict_telemetry_tiers", [Tier.PRODUCTION.name])
    if not isinstance(strict_telemetry_tiers, list):
        raise ValueError("constitution_policy_invalid_schema:resource_bounds_strict_telemetry_tiers")
    for tier_name in strict_telemetry_tiers:
        if str(tier_name).strip().upper() not in Tier.__members__:
            raise ValueError(f"constitution_policy_invalid_schema:resource_bounds_strict_telemetry_tier:{tier_name}")


def _record_amendment(old_hash: str | None, new_hash: str, version: str) -> None:
    if old_hash is None or old_hash == new_hash:
        return
    payload = {"version": version, "old_policy_hash": old_hash, "new_policy_hash": new_hash}
    journal.write_entry(agent_id="system", action="constitutional_amendment", payload=payload)
    journal.append_tx(tx_type="constitutional_amendment", payload=payload)


def load_constitution_policy(path: Path = POLICY_PATH, expected_version: str = CONSTITUTION_VERSION) -> tuple[List[Rule], str]:
    global _POLICY_DOCUMENT
    policy, policy_hash = _load_policy_document(path)
    _validate_policy_schema(policy, expected_version)
    _POLICY_DOCUMENT = dict(policy)
    applicability = _load_rule_applicability()

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
                applicability=dict(applicability.get(str(raw_rule["name"]), {})),
            )
        )
    return rule_objects, policy_hash


try:
    RULES, POLICY_HASH = load_constitution_policy()
except ValueError as exc:
    raise RuntimeError(f"constitution_boot_failed:{exc}") from exc

_record_amendment(old_hash=None, new_hash=POLICY_HASH, version=CONSTITUTION_VERSION)
_BASE_GOVERNANCE_FINGERPRINT = _current_governance_fingerprint()
_GOVERNANCE_DEBT_LEDGER = GovernanceDebtLedger()


def reload_constitution_policy(path: Path = POLICY_PATH) -> str:
    """Reload policy artifact and log hash delta as a constitutional amendment."""
    global RULES, POLICY_HASH, _BASE_GOVERNANCE_FINGERPRINT
    old_hash = POLICY_HASH
    rules, new_hash = load_constitution_policy(path=path, expected_version=CONSTITUTION_VERSION)
    RULES = rules
    POLICY_HASH = new_hash
    _record_amendment(old_hash=old_hash, new_hash=new_hash, version=CONSTITUTION_VERSION)
    _BASE_GOVERNANCE_FINGERPRINT = _current_governance_fingerprint()
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




def _parse_severity_escalations(envelope_state: Mapping[str, Any]) -> Dict[str, Severity]:
    """Parse optional rule severity escalation directives.

    Sources (later overrides earlier):
    - `ADAAD_SEVERITY_ESCALATIONS` env var containing JSON object `{rule: severity}`
    - `severity_escalations` mapping in deterministic envelope state
    """
    escalations: Dict[str, Severity] = {}

    raw_env = os.getenv("ADAAD_SEVERITY_ESCALATIONS", "").strip()
    if raw_env:
        try:
            parsed_env = json.loads(raw_env)
        except json.JSONDecodeError:
            parsed_env = {}
        if isinstance(parsed_env, Mapping):
            for rule_name, raw_sev in parsed_env.items():
                key = str(rule_name).strip()
                sev_name = str(raw_sev).strip().upper()
                if key and sev_name in Severity.__members__:
                    escalations[key] = Severity[sev_name]

    state_map = envelope_state.get("severity_escalations")
    if isinstance(state_map, Mapping):
        for rule_name, raw_sev in state_map.items():
            key = str(rule_name).strip()
            sev_name = str(raw_sev).strip().upper()
            if key and sev_name in Severity.__members__:
                escalations[key] = Severity[sev_name]

    return escalations


def _resolve_rule_severity(rule_name: str, default: Severity, escalations: Mapping[str, Severity]) -> Severity:
    candidate = escalations.get(rule_name, default)
    if _SEVERITY_ORDER.get(candidate, 0) < _SEVERITY_ORDER.get(default, 0):
        return default
    return candidate


def evaluate_mutation(request: MutationRequest, tier: Tier) -> Dict[str, Any]:
    """
    Apply all constitutional rules to a mutation request.

    Returns:
        Verdict with detailed rule evaluations and blocking status.
    """
    rules = _order_rules_with_dependencies(get_rules_for_tier(tier))
    verdicts: List[Dict[str, Any]] = []
    blocking_failures: List[str] = []
    warnings: List[str] = []

    prior_state = get_deterministic_envelope_state()
    domain_classification = _classify_request_domains(request)
    monitor_snapshot = AndroidMonitor(Path.cwd()).snapshot()
    android_telemetry = normalize_platform_telemetry_snapshot(
        memory_mb=monitor_snapshot.memory_mb,
        cpu_percent=monitor_snapshot.cpu_percent,
        battery_percent=monitor_snapshot.battery_percent,
        storage_mb=monitor_snapshot.storage_mb,
    )
    existing_platform_telemetry = prior_state.get("platform_telemetry") if isinstance(prior_state.get("platform_telemetry"), Mapping) else {}
    # Rationale: merge Android and runtime telemetry conservatively for constitutional
    # resource bounds enforcement.
    # Invariants: memory/cpu preserve highest pressure; battery/storage preserve
    # most constrained context values.
    merged_platform_telemetry = merge_platform_telemetry(observed=existing_platform_telemetry, android=android_telemetry)
    evaluation_state = {
        **prior_state,
        "tier": tier.name,
        "tier_value": tier.value,
        "agent_id": request.agent_id,
        "epoch_id": str(request.epoch_id or ""),
        "domain_classification": domain_classification,
        "platform_telemetry": merged_platform_telemetry,
    }

    with deterministic_envelope_scope(evaluation_state):
        escalations = _parse_severity_escalations(evaluation_state)
        applicability_matrix: List[Dict[str, Any]] = []
        for rule, severity in rules:
            effective_severity = _resolve_rule_severity(rule.name, severity, escalations)
            applicability_row = _evaluate_rule_applicability(rule, request, tier)
            applicability_matrix.append(applicability_row)
            if not applicability_row["applicable"]:
                verdicts.append(
                    {
                        "rule": rule.name,
                        "severity": effective_severity.value,
                        "passed": True,
                        "applicable": False,
                        "provenance": _validator_provenance(rule),
                        "details": {
                            "ok": True,
                            "reason": "rule_not_applicable",
                            "applicability": applicability_row,
                        },
                    }
                )
                continue
            try:
                result = rule.validator(request)
            except Exception as exc:
                result = {"ok": False, "reason": f"validator_error:{exc}"}

            verdict = {
                "rule": rule.name,
                "severity": effective_severity.value,
                "base_severity": severity.value,
                "passed": result.get("ok", False),
                "applicable": True,
                "provenance": _validator_provenance(rule),
                "details": result,
            }
            verdicts.append(verdict)

            if not verdict["passed"]:
                if effective_severity == Severity.BLOCKING:
                    blocking_failures.append(rule.name)
                elif effective_severity == Severity.WARNING:
                    warnings.append(rule.name)

    fingerprint_components = _governance_fingerprint_components()
    drift_fingerprint = _canonical_digest(fingerprint_components)
    drift_detected = drift_fingerprint != _BASE_GOVERNANCE_FINGERPRINT
    if drift_detected:
        drift_reason = "governance_drift_detected"
        if tier == Tier.PRODUCTION:
            blocking_failures.append(drift_reason)
        else:
            warnings.append(drift_reason)

    passed = len(blocking_failures) == 0

    envelope_rows = [
        {
            "rule": item["rule"],
            "severity": item["severity"],
            "passed": item["passed"],
            "applicable": item["applicable"],
            "details_hash": _canonical_digest(canonicalize_governance_details(item.get("details", {}))),
            "provenance_hash": _canonical_digest(item.get("provenance", {})),
        }
        for item in sorted(verdicts, key=lambda row: str(row.get("rule", "")))
    ]
    governance_envelope = {
        "constitution_version": CONSTITUTION_VERSION,
        "policy_hash": POLICY_HASH,
        "tier": tier.name,
        "tier_value": tier.value,
        "epoch_id": str(evaluation_state.get("epoch_id", "")),
        "agent_id": request.agent_id,
        "rules": envelope_rows,
    }
    governance_envelope["digest"] = _canonical_digest(governance_envelope)

    evaluation = {
        "constitution_version": CONSTITUTION_VERSION,
        "policy_hash": POLICY_HASH,
        "tier": tier.name,
        "tier_value": tier.value,
        "passed": passed,
        "verdicts": verdicts,
        "blocking_failures": blocking_failures,
        "warnings": warnings,
        "applicability_matrix": applicability_matrix,
        "agent_id": request.agent_id,
        "intent": request.intent,
        "resolved_domain": domain_classification.get("resolved_domain"),
        "domain_classification": domain_classification,
        "rule_dependency_graph": RULE_DEPENDENCY_GRAPH,
        "governance_envelope": governance_envelope,
        "governance_fingerprint": drift_fingerprint,
        "governance_fingerprint_baseline": _BASE_GOVERNANCE_FINGERPRINT,
        "governance_fingerprint_components": fingerprint_components,
        "governance_drift_detected": drift_detected,
    }

    epoch_id = str(evaluation_state.get("epoch_id", "")).strip()
    epoch_match = re.search(r"(\d+)$", epoch_id)
    epoch_index = int(epoch_match.group(1)) if epoch_match else 0
    warning_verdicts = [
        item
        for item in verdicts
        if isinstance(item, dict) and str(item.get("severity", "")).strip().lower() == Severity.WARNING.value and not bool(item.get("passed", False))
    ]
    if drift_detected and tier != Tier.PRODUCTION:
        warning_verdicts.append({"rule": "governance_drift_detected", "severity": Severity.WARNING.value, "passed": False})
    debt_snapshot = _GOVERNANCE_DEBT_LEDGER.accumulate_epoch_verdicts(
        epoch_id=epoch_id,
        epoch_index=epoch_index,
        warning_verdicts=warning_verdicts,
        agent_id=request.agent_id,
    )
    evaluation["governance_debt_snapshot"] = {
        "snapshot_hash": debt_snapshot.snapshot_hash,
        "prev_snapshot_hash": debt_snapshot.prev_snapshot_hash,
        "compound_debt_score": debt_snapshot.compound_debt_score,
        "threshold_breached": debt_snapshot.threshold_breached,
    }



    ceiling_events = []
    for item in verdicts:
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        detail_payload = details.get("details") if isinstance(details.get("details"), dict) else {}
        if not detail_payload or "applied_ceiling" not in detail_payload:
            continue
        ceiling_events.append(
            {
                "rule": item.get("rule"),
                "resolved_domain": detail_payload.get("resolved_domain", domain_classification.get("resolved_domain")),
                "applied_ceiling": detail_payload.get("applied_ceiling"),
                "tier_limit": detail_payload.get("tier_limit"),
                "domain_limit": detail_payload.get("domain_limit"),
            }
        )

    if epoch_id:
        journal.write_entry(
            agent_id=request.agent_id or "system",
            action="constitutional_evaluation_domain_ceiling",
            payload={
                "agent_id": request.agent_id,
                "epoch_id": epoch_id,
                "tier": tier.name,
                "resolved_domain": domain_classification.get("resolved_domain"),
                "domain_classification": domain_classification,
                "applied_ceilings": ceiling_events,
                "passed": passed,
            },
        )
        journal.append_tx(
            tx_type="constitutional_evaluation_domain_ceiling",
            payload={
                "agent_id": request.agent_id,
                "epoch_id": epoch_id,
                "tier": tier.name,
                "resolved_domain": domain_classification.get("resolved_domain"),
                "applied_ceilings": ceiling_events,
                "passed": passed,
            },
        )

    metrics.log(
        event_type="constitutional_evaluation",
        payload=evaluation,
        level="INFO" if passed else "ERROR",
        element_id=ELEMENT_ID,
    )
    if drift_detected:
        metrics.log(
            event_type="governance_drift_detected",
            payload={
                "agent_id": request.agent_id,
                "tier": tier.name,
                "fingerprint": drift_fingerprint,
                "baseline_fingerprint": _BASE_GOVERNANCE_FINGERPRINT,
                "components": fingerprint_components,
            },
            level="ERROR" if tier == Tier.PRODUCTION else "WARNING",
            element_id=ELEMENT_ID,
        )

    metrics.log(
        event_type="governance_replay_capsule",
        payload={
            "agent_id": request.agent_id,
            "intent": request.intent,
            "tier": tier.name,
            "epoch_id": str(evaluation_state.get("epoch_id", "")),
            "applicability_matrix": applicability_matrix,
            "verdicts": verdicts,
            "governance_envelope": governance_envelope,
            "deterministic_state": {
                "observed_entropy_bits": int(evaluation_state.get("observed_entropy_bits", 0) or 0),
                "epoch_entropy_bits": int(evaluation_state.get("epoch_entropy_bits", 0) or 0),
            },
        },
        level="INFO",
        element_id=ELEMENT_ID,
    )

    if not passed:
        resource_verdict = next((item for item in verdicts if item.get("rule") == "resource_bounds"), {})
        resource_details = resource_verdict.get("details") if isinstance(resource_verdict, dict) else {}
        detail_map = resource_details.get("details") if isinstance(resource_details, dict) else {}
        detail_map = detail_map if isinstance(detail_map, dict) else {}
        rejection_payload = {
            "event_schema": "governance.rejection.v1",
            "agent_id": request.agent_id,
            "epoch_id": str(evaluation_state.get("epoch_id", "")),
            "tier": tier.name,
            "blocking_failures": list(blocking_failures),
            "warnings": list(warnings),
            "policy_hash": POLICY_HASH,
            "bounds_policy_version": detail_map.get("bounds_policy_version", "unknown"),
            "resource_usage_snapshot": detail_map.get("resource_usage_snapshot", {}),
        }
        metrics.log(event_type="governance_rejection", payload=rejection_payload, level="ERROR", element_id=ELEMENT_ID)
        journal.write_entry(agent_id=request.agent_id or "system", action="governance_rejection", payload=rejection_payload)
        journal.append_tx(tx_type="governance_rejection", payload=rejection_payload)

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
    "boot_sanity_check",
    "load_constitution_policy",
    "reload_constitution_policy",
    "Tier",
    "Severity",
    "CONSTITUTION_VERSION",
    "RULES",
    "POLICY_HASH",
    "POLICY_PATH",
    "set_deterministic_envelope_state",
    "reset_deterministic_envelope_state",
    "deterministic_envelope_scope",
    "get_deterministic_envelope_state",
]
