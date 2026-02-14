# SPDX-License-Identifier: Apache-2.0
"""Founders Law authority module for invariant/governance evaluations."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping

from runtime import ROOT_DIR, metrics
from security.ledger import journal

LAW_NAME = "founders_law"
LAW_VERSION = "founders_law@epoch-v1"
LAW_EPOCH_METADATA_KEY = "law_version"

RULE_INVARIANT_TREE = "FL-INVARIANT-TREE-V1"
RULE_INVARIANT_IMPORTS = "FL-INVARIANT-IMPORTS-V1"
RULE_INVARIANT_ABS_PATHS = "FL-INVARIANT-ABS-PATHS-V1"
RULE_INVARIANT_METRICS = "FL-INVARIANT-METRICS-V1"
RULE_INVARIANT_SECURITY = "FL-INVARIANT-SECURITY-V1"
RULE_INVARIANT_STAGING = "FL-INVARIANT-STAGING-V1"
RULE_INVARIANT_CAPABILITIES = "FL-INVARIANT-CAPABILITIES-V1"
RULE_CONSTITUTION_VERSION = "FL-CONSTITUTION-VERSION-V1"
RULE_KEY_ROTATION = "FL-KEY-ROTATION-V1"
RULE_LEDGER_INTEGRITY = "FL-LEDGER-INTEGRITY-V1"
RULE_MUTATION_ENGINE = "FL-MUTATION-ENGINE-V1"
RULE_WARM_POOL = "FL-WARM-POOL-V1"
RULE_ARCHITECT_SCAN = "FL-ARCHITECT-SCAN-V1"
RULE_PLATFORM_RESOURCES = "FL-PLATFORM-RESOURCES-V1"

REASON_PASS = "LAW_PASS"
REASON_FAIL_RULE = "LAW_RULE_FAILED"
LAW_POLICY_PATH = ROOT_DIR / "runtime" / "governance" / "founders_law.json"


@dataclass(frozen=True)
class LawRule:
    rule_id: str
    version: str
    name: str
    enabled: bool = True
    severity: str = "blocking"


DEFAULT_LAW_RULES: Dict[str, LawRule] = {
    rule.rule_id: rule
    for rule in [
        LawRule(RULE_INVARIANT_TREE, "1.0.0", "required_tree_layout"),
        LawRule(RULE_INVARIANT_IMPORTS, "1.0.0", "banned_import_roots"),
        LawRule(RULE_INVARIANT_ABS_PATHS, "1.0.0", "absolute_path_guard"),
        LawRule(RULE_INVARIANT_METRICS, "1.0.0", "metrics_pipeline_access"),
        LawRule(RULE_INVARIANT_SECURITY, "1.0.0", "security_path_integrity"),
        LawRule(RULE_INVARIANT_STAGING, "1.0.0", "staging_directory_available"),
        LawRule(RULE_INVARIANT_CAPABILITIES, "1.0.0", "capabilities_json_valid"),
        LawRule(RULE_CONSTITUTION_VERSION, "1.0.0", "constitution_version_match"),
        LawRule(RULE_KEY_ROTATION, "1.0.0", "key_rotation_freshness", severity="warning"),
        LawRule(RULE_LEDGER_INTEGRITY, "1.0.0", "ledger_integrity_chain"),
        LawRule(RULE_MUTATION_ENGINE, "1.0.0", "mutation_engine_health"),
        LawRule(RULE_WARM_POOL, "1.0.0", "warm_pool_ready"),
        LawRule(RULE_ARCHITECT_SCAN, "1.0.0", "architect_scan_valid"),
        LawRule(RULE_PLATFORM_RESOURCES, "1.0.0", "platform_resources_ok"),
    ]
}

LAW_RULES: Dict[str, LawRule] = dict(DEFAULT_LAW_RULES)
_POLICY_CACHE_MTIME: float | None = None


@dataclass(frozen=True)
class LawDecision:
    passed: bool
    decision: str
    reason_codes: List[str]
    rule_ids_evaluated: List[str]
    law_version: str = LAW_VERSION
    failed_rules: List[Dict[str, str]] = field(default_factory=list)


def epoch_law_metadata() -> Dict[str, str]:
    return {LAW_EPOCH_METADATA_KEY: LAW_VERSION}


def load_law_policy(path: Path = LAW_POLICY_PATH) -> Dict[str, LawRule]:
    if not path.exists():
        return dict(DEFAULT_LAW_RULES)
    raw = json.loads(path.read_text(encoding="utf-8"))
    loaded: Dict[str, LawRule] = dict(DEFAULT_LAW_RULES)
    for rule in raw.get("rules", []):
        rule_id = str(rule.get("rule_id") or "").strip()
        if not rule_id:
            continue
        base = loaded.get(rule_id, LawRule(rule_id=rule_id, version="1.0.0", name=rule_id))
        loaded[rule_id] = LawRule(
            rule_id=rule_id,
            version=str(rule.get("version") or base.version),
            name=str(rule.get("name") or base.name),
            enabled=bool(rule.get("enabled", base.enabled)),
            severity=str(rule.get("severity") or base.severity).lower(),
        )
    return loaded


def reload_founders_law(force: bool = False) -> Dict[str, LawRule]:
    global LAW_RULES, _POLICY_CACHE_MTIME
    policy_path = LAW_POLICY_PATH
    mtime = policy_path.stat().st_mtime if policy_path.exists() else None
    if not force and _POLICY_CACHE_MTIME == mtime:
        return LAW_RULES
    LAW_RULES = load_law_policy(policy_path)
    _POLICY_CACHE_MTIME = mtime
    return LAW_RULES


def _rule(rule_id: str) -> LawRule:
    return LAW_RULES.get(rule_id, LawRule(rule_id=rule_id, version="1.0.0", name=rule_id))


def enforce_law(context: Mapping[str, Any]) -> LawDecision:
    reload_founders_law(force=False)
    checks = list(context.get("checks") or [])
    mutation_id = str(context.get("mutation_id") or "unknown")
    trust_mode = str(context.get("trust_mode") or "standard")
    failed_rules: List[Dict[str, str]] = []
    evaluated_rule_ids: List[str] = []

    for check in checks:
        rule_id = str(check.get("rule_id") or "")
        if not rule_id:
            continue
        cfg = _rule(rule_id)
        if not cfg.enabled:
            continue
        evaluated_rule_ids.append(rule_id)
        ok = bool(check.get("ok", False))
        if (not ok) and cfg.severity == "blocking":
            failed_rules.append({"rule_id": rule_id, "reason": str(check.get("reason") or "failed")})

    passed = len(failed_rules) == 0
    decision = "pass" if passed else "fail"
    reason_codes = [REASON_PASS] if passed else [REASON_FAIL_RULE] + [item["rule_id"] for item in failed_rules]
    law_decision = LawDecision(
        passed=passed,
        decision=decision,
        reason_codes=reason_codes,
        rule_ids_evaluated=evaluated_rule_ids,
        failed_rules=failed_rules,
    )

    lineage_payload = {
        "mutation_id": mutation_id,
        "law_version": LAW_VERSION,
        "rule_ids_evaluated": evaluated_rule_ids,
        "decision": decision,
        "trust_mode": trust_mode,
        "reason_codes": reason_codes,
    }
    metrics.log(event_type="founders_law_evaluated", payload=lineage_payload, level="INFO")
    try:
        from runtime.evolution.lineage_v2 import LineageLedgerV2

        LineageLedgerV2().append_event("FoundersLawEvaluationEvent", lineage_payload)
    except Exception:
        pass
    try:
        journal.append_tx(tx_type="founders_law_evaluation", payload=lineage_payload)
    except Exception:
        pass
    return law_decision


__all__ = [
    "LAW_VERSION",
    "LAW_EPOCH_METADATA_KEY",
    "LAW_POLICY_PATH",
    "LAW_RULES",
    "DEFAULT_LAW_RULES",
    "LawDecision",
    "LawRule",
    "enforce_law",
    "epoch_law_metadata",
    "load_law_policy",
    "reload_founders_law",
    "RULE_INVARIANT_TREE",
    "RULE_INVARIANT_IMPORTS",
    "RULE_INVARIANT_ABS_PATHS",
    "RULE_INVARIANT_METRICS",
    "RULE_INVARIANT_SECURITY",
    "RULE_INVARIANT_STAGING",
    "RULE_INVARIANT_CAPABILITIES",
    "RULE_CONSTITUTION_VERSION",
    "RULE_KEY_ROTATION",
    "RULE_LEDGER_INTEGRITY",
    "RULE_MUTATION_ENGINE",
    "RULE_WARM_POOL",
    "RULE_ARCHITECT_SCAN",
    "RULE_PLATFORM_RESOURCES",
]
