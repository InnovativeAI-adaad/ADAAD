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
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping

from app.agents.mutation_request import MutationRequest
from runtime import metrics
from security.ledger import journal

CONSTITUTION_VERSION = "0.2.0"
ELEMENT_ID = "Earth"
POLICY_PATH = Path("runtime/governance/constitution.yaml")
RULE_APPLICABILITY_PATH = Path("governance/rule_applicability.yaml")
_DETERMINISTIC_ENVELOPE_STATE: ContextVar[Dict[str, Any]] = ContextVar("deterministic_envelope_state", default={})

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
    "_validate_lineage": "2.1.0",
    "_validate_complexity": "1.1.0",
    "_validate_coverage": "1.1.0",
    "_validate_mutation_rate": "2.1.0",
    "_validate_resources": "1.1.0",
    "_validate_entropy_budget_limit": "1.0.0",
}
_LINEAGE_VALIDATION_CACHE: Dict[str, Any] = {}


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


def _validate_lineage(_: MutationRequest) -> Dict[str, Any]:
    """Resolve and verify append-only lineage chain up to certified genesis."""
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
            chain.append(
                {
                    "source": source_name,
                    "path": str(path),
                    "line": line_no,
                    "tx": str(entry.get("tx") or ""),
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

    def _safe_float(value: Any) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if parsed < 0:
            return 0.0
        return parsed

    envelope_state = get_deterministic_envelope_state()
    telemetry = envelope_state.get("platform_telemetry")
    observed = envelope_state.get("resource_measurements")
    observed_map = observed if isinstance(observed, Mapping) else {}
    telemetry_map = telemetry if isinstance(telemetry, Mapping) else {}

    memory_limit_mb, bad_memory_bound = _bound_from_env("ADAAD_RESOURCE_MEMORY_MB", 2048.0)
    cpu_limit_s, bad_cpu_bound = _bound_from_env("ADAAD_RESOURCE_CPU_SECONDS", 30.0)
    wall_limit_s, bad_wall_bound = _bound_from_env("ADAAD_RESOURCE_WALL_SECONDS", 60.0)
    if bad_memory_bound is not None:
        return {"ok": False, "reason": "invalid_resource_memory_bound", "details": {"value": bad_memory_bound}}
    if bad_cpu_bound is not None:
        return {"ok": False, "reason": "invalid_resource_cpu_bound", "details": {"value": bad_cpu_bound}}
    if bad_wall_bound is not None:
        return {"ok": False, "reason": "invalid_resource_wall_bound", "details": {"value": bad_wall_bound}}

    rss_candidates = [
        _safe_float(observed_map.get("peak_rss_mb")),
        _safe_float(observed_map.get("memory_mb")),
        _safe_float(telemetry_map.get("memory_mb")),
    ]
    cpu_candidates = [_safe_float(observed_map.get("cpu_seconds")), _safe_float(observed_map.get("cpu_time_seconds"))]
    wall_candidates = [
        _safe_float(observed_map.get("wall_seconds")),
        _safe_float(observed_map.get("wall_time_seconds")),
    ]

    if not any(value is not None for value in rss_candidates):
        rss_candidates.append(0.0)
    if not any(value is not None for value in cpu_candidates):
        cpu_candidates.append(0.0)
    if not any(value is not None for value in wall_candidates):
        wall_candidates.append(0.0)

    peak_rss_mb = max((value for value in rss_candidates if value is not None), default=0.0)
    cpu_seconds = max((value for value in cpu_candidates if value is not None), default=0.0)
    wall_seconds = max((value for value in wall_candidates if value is not None), default=0.0)

    memory_exceeded = memory_limit_mb > 0 and peak_rss_mb > memory_limit_mb
    cpu_exceeded = cpu_limit_s > 0 and cpu_seconds > cpu_limit_s
    wall_exceeded = wall_limit_s > 0 and wall_seconds > wall_limit_s
    exceeded = memory_exceeded or cpu_exceeded or wall_exceeded

    details = {
        "limits": {
            "memory_mb": round(memory_limit_mb, 4),
            "cpu_seconds": round(cpu_limit_s, 4),
            "wall_seconds": round(wall_limit_s, 4),
        },
        "observed": {
            "peak_rss_mb": round(peak_rss_mb, 4),
            "cpu_seconds": round(cpu_seconds, 4),
            "wall_seconds": round(wall_seconds, 4),
        },
        "telemetry": {
            "memory_mb": _safe_float(telemetry_map.get("memory_mb")),
            "cpu_percent": _safe_float(telemetry_map.get("cpu_percent")),
            "battery_percent": _safe_float(telemetry_map.get("battery_percent")),
            "storage_mb": _safe_float(telemetry_map.get("storage_mb")),
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


def set_deterministic_envelope_state(state: Mapping[str, Any] | None) -> Token[Dict[str, Any]]:
    """Set request-scoped deterministic envelope context for validators."""
    return _DETERMINISTIC_ENVELOPE_STATE.set(dict(state or {}))


def reset_deterministic_envelope_state(token: Token[Dict[str, Any]]) -> None:
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
    return dict(_DETERMINISTIC_ENVELOPE_STATE.get() or {})


def _parse_entropy_limit(value: str, *, field: str) -> tuple[bool, int, str | None]:
    try:
        parsed = int(value)
    except ValueError:
        return False, 0, f"invalid_{field}"
    return True, parsed, None


def _validate_entropy_budget_limit(request: MutationRequest) -> Dict[str, Any]:
    """Reject requests whose mutation/epoch entropy exceeds configured constitutional budgets."""
    from runtime.evolution.entropy_metadata import estimate_entropy_bits

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

    mutation_exceeded = mutation_bits > max_mutation_bits
    epoch_exceeded = epoch_bits > max_epoch_bits
    if mutation_exceeded and epoch_exceeded:
        reason = "mutation_and_epoch_entropy_budget_exceeded"
    elif mutation_exceeded:
        reason = "entropy_budget_exceeded"
    elif epoch_exceeded:
        reason = "epoch_entropy_budget_exceeded"
    else:
        reason = "entropy_budget_ok"

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
            "declared_bits": declared_bits,
            "observed_bits": observed_bits,
            "mutation_bits": mutation_bits,
            "epoch_entropy_bits": epoch_bits,
            "mutation_exceeded": mutation_exceeded,
            "epoch_exceeded": epoch_exceeded,
        },
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
    evaluation_state = {
        **prior_state,
        "tier": tier.name,
        "tier_value": tier.value,
        "agent_id": request.agent_id,
        "epoch_id": str(request.epoch_id or ""),
        "domain_classification": domain_classification,
    }

    with deterministic_envelope_scope(evaluation_state):
        applicability_matrix: List[Dict[str, Any]] = []
        for rule, severity in rules:
            applicability_row = _evaluate_rule_applicability(rule, request, tier)
            applicability_matrix.append(applicability_row)
            if not applicability_row["applicable"]:
                verdicts.append(
                    {
                        "rule": rule.name,
                        "severity": severity.value,
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
                "severity": severity.value,
                "passed": result.get("ok", False),
                "applicable": True,
                "provenance": _validator_provenance(rule),
                "details": result,
            }
            verdicts.append(verdict)

            if not verdict["passed"]:
                if severity == Severity.BLOCKING:
                    blocking_failures.append(rule.name)
                elif severity == Severity.WARNING:
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
            "details_hash": _canonical_digest(item.get("details", {})),
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

    epoch_id = str(evaluation_state.get("epoch_id", "")).strip()
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
    "set_deterministic_envelope_state",
    "reset_deterministic_envelope_state",
    "deterministic_envelope_scope",
    "get_deterministic_envelope_state",
]
