# SPDX-License-Identifier: Apache-2.0
"""Deterministic blocked-state remediation metadata and formatters."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping


@dataclass(frozen=True)
class RemediationMetadata:
    gate_id: str
    gate_type: str
    minimal_repro_command: str
    expected_pass_condition: str
    probable_root_causes: tuple[str, ...]
    next_allowed_action: str


_REMEDIATION_BY_GATE: dict[str, RemediationMetadata] = {
    "TIER0_SCHEMA_VALIDATION": RemediationMetadata(
        gate_id="TIER0_SCHEMA_VALIDATION",
        gate_type="tier0",
        minimal_repro_command="python scripts/validate_governance_schemas.py",
        expected_pass_condition="exit_code=0 and output contains governance_schema_validation:ok",
        probable_root_causes=(
            "schema contract drift in docs/schemas",
            "invalid or missing required governance fields",
            "invocation from non-repository working directory",
        ),
        next_allowed_action="Correct schema payloads and rerun Tier 0 baseline.",
    ),
    "ABILITIES_DRIFT": RemediationMetadata(
        gate_id="ABILITIES_DRIFT",
        gate_type="self",
        minimal_repro_command="python -m app.main --abilities-drift or from adaad.abilities.drift import detect_abilities_drift; report=detect_abilities_drift()",
        expected_pass_condition="parity_ok=True and len(drifted)==0 for self_abilities surface",
        probable_root_causes=(
            "seed (capabilities.json) vs registry mismatch after clear or partial bootstrap",
            "new discovered abilities not yet promoted via governance hook / CMES",
            "drift in meta abilities (introspect, drift_hygiene, self_register, enhance) post state changes",
        ),
        next_allowed_action="Run seed_from_capabilities_json(); reconcile with detect_and_reconcile_drift(); or use --list-abilities to verify. Escalate to self-enhance proposal if persistent.",
    ),
    "TIER0_ARCHITECTURE_SNAPSHOT": RemediationMetadata(
        gate_id="TIER0_ARCHITECTURE_SNAPSHOT",
        gate_type="tier0",
        minimal_repro_command="python scripts/validate_architecture_snapshot.py",
        expected_pass_condition="exit_code=0 and output contains architecture snapshot metadata OK",
        probable_root_causes=(
            "architecture snapshot file drift",
            "missing snapshot metadata keys",
            "stale generated snapshot artifact",
        ),
        next_allowed_action="Regenerate/fix architecture snapshot artifacts and rerun Tier 0 baseline.",
    ),
    "TIER0_DETERMINISM_LINT": RemediationMetadata(
        gate_id="TIER0_DETERMINISM_LINT",
        gate_type="tier0",
        minimal_repro_command="python tools/lint_determinism.py runtime/ security/ adaad/orchestrator/ app/main.py",
        expected_pass_condition="exit_code=0 and no forbidden_dynamic_execution or entropy violations",
        probable_root_causes=(
            "nondeterministic API usage introduced in governed paths",
            "dynamic execution detected (exec/eval/command construction)",
            "new entropy source missing ENTROPY_ALLOWLIST justification",
        ),
        next_allowed_action="Remove nondeterministic behavior or add approved deterministic control, then rerun Tier 0.",
    ),
    "TIER0_IMPORT_BOUNDARY_LINT": RemediationMetadata(
        gate_id="TIER0_IMPORT_BOUNDARY_LINT",
        gate_type="tier0",
        minimal_repro_command="python tools/lint_import_paths.py",
        expected_pass_condition="exit_code=0 and no forbidden import-boundary violations",
        probable_root_causes=(
            "cross-layer import violates architecture contract",
            "legacy import path left after refactor",
            "new module imported from restricted tier",
        ),
        next_allowed_action="Fix import boundaries and rerun Tier 0.",
    ),
    "TIER0_FAST_CONFIDENCE_TESTS": RemediationMetadata(
        gate_id="TIER0_FAST_CONFIDENCE_TESTS",
        gate_type="tier0",
        minimal_repro_command="PYTHONPATH=. pytest tests/determinism/ tests/recovery/test_tier_manager.py -k \"not shared_epoch_parallel_validation_is_deterministic_in_strict_mode\" -q",
        expected_pass_condition="exit_code=0 with no failed tests",
        probable_root_causes=(
            "determinism regression in runtime path",
            "fixture drift in recovery/tier manager tests",
            "missing development dependency for test execution",
        ),
        next_allowed_action="Fix failing test root cause and rerun Tier 0 fast confidence tests.",
    ),
    "TIER1_FULL_TEST_SUITE": RemediationMetadata(
        gate_id="TIER1_FULL_TEST_SUITE",
        gate_type="tier1",
        minimal_repro_command="PYTHONPATH=. pytest tests/ -q",
        expected_pass_condition="exit_code=0 with all tests passed and zero failures",
        probable_root_causes=(
            "functional regression introduced by current diff",
            "nondeterministic behavior causing flaky assertions",
            "environment dependency mismatch with repository requirements",
        ),
        next_allowed_action="Fix implementation or environment drift, then rerun full Tier 1 test suite.",
    ),
    "TIERM_WORKING_CODE_ASSERTION": RemediationMetadata(
        gate_id="TIERM_WORKING_CODE_ASSERTION",
        gate_type="tier_m",
        minimal_repro_command="PYTHONPATH=. pytest tests/ -q",
        expected_pass_condition="merge SHA test run has 0 failed tests and 0 skipped tests in scope",
        probable_root_causes=(
            "merge SHA differs from verified branch SHA",
            "hidden integration regression not covered by partial checks",
            "test skip/xfail policy violation in changed files",
        ),
        next_allowed_action="Re-run full Tier 0-3 and Tier M gates on merge SHA; merge remains blocked until green.",
    ),
}

_STATUS_ALLOWED = {"[ADAAD BLOCKED]", "[ADAAD WAITING]", "[DEVADAAD MERGE-BLOCKED]"}


def remediation_for_gate(gate_id: str) -> RemediationMetadata:
    try:
        return _REMEDIATION_BY_GATE[gate_id]
    except KeyError as exc:
        raise KeyError(f"unknown_gate_id:{gate_id}") from exc


def format_blocked_state(status: str, gate_id: str, failure_detail: str, action_required: str | None = None) -> str:
    if status not in _STATUS_ALLOWED:
        raise ValueError(f"unsupported_status:{status}")
    remediation = remediation_for_gate(gate_id)
    action = action_required.strip() if action_required else remediation.next_allowed_action
    payload: Mapping[str, object] = {
        "status": status.strip("[]"),
        "gate_id": remediation.gate_id,
        "gate_type": remediation.gate_type,
        "minimal_repro_command": remediation.minimal_repro_command,
        "expected_pass_condition": remediation.expected_pass_condition,
        "probable_root_causes": list(remediation.probable_root_causes),
        "failure_detail": failure_detail,
        "next_allowed_action": remediation.next_allowed_action,
        "action_required": action,
    }
    return "\n".join(
        (
            status,
            f"Gate:            {remediation.gate_id}",
            f"Failure:         {failure_detail}",
            f"Command:         {remediation.minimal_repro_command}",
            f"Expected pass:   {remediation.expected_pass_condition}",
            "Probable causes: " + " | ".join(remediation.probable_root_causes),
            f"Action required: {action}",
            "Remediation JSON: " + json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )
    )


def gate_id_for_tier0_check(check_name: str) -> str:
    normalized = check_name.strip().lower()
    mapping = {
        "schema validation": "TIER0_SCHEMA_VALIDATION",
        "architecture snapshot": "TIER0_ARCHITECTURE_SNAPSHOT",
        "determinism lint": "TIER0_DETERMINISM_LINT",
        "import boundary lint": "TIER0_IMPORT_BOUNDARY_LINT",
        "fast confidence tests": "TIER0_FAST_CONFIDENCE_TESTS",
    }
    try:
        return mapping[normalized]
    except KeyError as exc:
        raise KeyError(f"unknown_tier0_check:{check_name}") from exc
