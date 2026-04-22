# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations
import pytest
pytestmark = pytest.mark.governance_gate

from dataclasses import dataclass

from runtime.governance.gate import (
    GOVERNANCE_DECISION_SCHEMA,
    DeterministicAxisEvaluator,
    GateAxisResult,
    GovernanceGate,
    canonical_evaluator_order,
    declared_policy_artifact_rule_ids,
    registered_runtime_check_ids,
)


@dataclass(frozen=True)
class _LawDecisionStub:
    passed: bool
    decision: str
    reason_codes: list[str]
    failed_rules: list[dict[str, str]]


def _checks_backed_law(ctx: dict[str, object]) -> _LawDecisionStub:
    checks = list(ctx.get("checks") or [])
    failed = [
        {"rule_id": str(row.get("rule_id") or ""), "reason": str(row.get("reason") or "failed")}
        for row in checks
        if not bool(row.get("ok", False)) and str(row.get("rule_id") or "")
    ]
    if failed:
        return _LawDecisionStub(
            passed=False,
            decision="fail",
            reason_codes=["LAW_RULE_FAILED"] + [row["rule_id"] for row in failed],
            failed_rules=failed,
        )
    return _LawDecisionStub(
        passed=True,
        decision="pass",
        reason_codes=["LAW_PASS"],
        failed_rules=[],
    )


def test_governance_gate_decision_schema_and_ledger_event() -> None:
    writes: list[tuple[str, dict[str, object]]] = []

    gate = GovernanceGate(
        law_enforcer=lambda _ctx: _LawDecisionStub(
            passed=True,
            decision="pass",
            reason_codes=["pass"],
            failed_rules=[],
        ),
        tx_writer=lambda tx_type, payload: writes.append((tx_type, payload)) or {"type": tx_type, "payload": payload},
    )

    decision = gate.approve_mutation(
        mutation_id="governance-gate-epoch-1",
        trust_mode="dev",
        axis_results=[
            GateAxisResult(axis="constitution_version", rule_id="rule.constitution", ok=True, reason="ok"),
            GateAxisResult(axis="ledger_integrity", rule_id="rule.ledger", ok=True, reason="ok"),
        ],
    )

    payload = decision.to_payload()
    assert decision.approved is True
    assert decision.decision == "pass"
    assert payload["mutation_id"] == "governance-gate-epoch-1"
    assert payload["trust_mode"] == "dev"
    assert payload["reason_codes"] == ["pass"]
    assert isinstance(payload["axis_results"], list)
    assert payload["axis_results"][0]["axis"] == "constitution_version"
    assert payload["axis_results"][1]["axis"] == "ledger_integrity"
    assert len(decision.decision_id) == 71

    assert [entry[0] for entry in writes] == ["governance_gate_decision.v1"]


def test_governance_gate_human_override_writes_override_tx() -> None:
    writes: list[tuple[str, dict[str, object]]] = []

    gate = GovernanceGate(
        law_enforcer=lambda _ctx: _LawDecisionStub(
            passed=False,
            decision="fail",
            reason_codes=["blocked"],
            failed_rules=[{"rule_id": "rule.ledger", "reason": "corrupt"}],
        ),
        tx_writer=lambda tx_type, payload: writes.append((tx_type, payload)) or {"type": tx_type, "payload": payload},
    )

    decision = gate.approve_mutation(
        mutation_id="governance-gate-epoch-2",
        trust_mode="prod",
        axis_results=[GateAxisResult(axis="ledger_integrity", rule_id="rule.ledger", ok=False, reason="corrupt")],
        human_override=True,
    )

    assert decision.approved is True
    assert decision.decision == "override_pass"
    assert "human_override" in decision.reason_codes
    assert [entry[0] for entry in writes] == [
        "governance_gate_decision.v1",
        "governance_gate_human_override.v1",
    ]


def test_governance_gate_decision_id_is_deterministic_for_same_inputs() -> None:
    gate = GovernanceGate(
        law_enforcer=lambda _ctx: _LawDecisionStub(
            passed=True,
            decision="pass",
            reason_codes=["pass"],
            failed_rules=[],
        ),
        tx_writer=lambda _tx_type, _payload: {},
    )

    axes_a = [
        GateAxisResult(axis="warm_pool", rule_id="rule.warm_pool", ok=True, reason="ok"),
        GateAxisResult(axis="constitution_version", rule_id="rule.constitution", ok=True, reason="ok"),
    ]
    axes_b = list(reversed(axes_a))

    first = gate.approve_mutation(mutation_id="governance-gate-epoch-3", trust_mode="audit", axis_results=axes_a)
    second = gate.approve_mutation(mutation_id="governance-gate-epoch-3", trust_mode="audit", axis_results=axes_b)

    assert first.to_payload() == second.to_payload()
    assert first.decision_id == second.decision_id


def test_governance_gate_emits_declared_runtime_checks_when_axis_not_supplied() -> None:
    gate = GovernanceGate(
        law_enforcer=lambda _ctx: _LawDecisionStub(
            passed=True,
            decision="pass",
            reason_codes=["pass"],
            failed_rules=[],
        ),
        tx_writer=lambda _tx_type, _payload: {},
    )

    decision = gate.approve_mutation(
        mutation_id="governance-gate-epoch-4",
        mutation_payload={"mutation_id": "governance-gate-epoch-4"},
        mutation_context={"rule_outcomes": {"signature_required": {"ok": False, "reason": "invalid_signature"}}},
    )

    assert decision.axis_results
    observed = {row.rule_id for row in decision.axis_results}
    assert observed == registered_runtime_check_ids()
    signature_row = next(row for row in decision.axis_results if row.rule_id == "signature_required")
    assert signature_row.ok is False
    assert signature_row.reason == "invalid_signature"


def test_canonical_evaluator_order_is_axis_then_rule_id() -> None:
    ordered = canonical_evaluator_order(
        [
            DeterministicAxisEvaluator(axis="z", rule_id="r3", probe=lambda: (True, "ok")),
            DeterministicAxisEvaluator(axis="a", rule_id="r2", probe=lambda: (True, "ok")),
            DeterministicAxisEvaluator(axis="a", rule_id="r1", probe=lambda: (True, "ok")),
        ]
    )
    assert [(row.axis, row.rule_id) for row in ordered] == [("a", "r1"), ("a", "r2"), ("z", "r3")]


def test_governance_decision_schema_contains_required_fields() -> None:
    required = set(GOVERNANCE_DECISION_SCHEMA["required"])
    assert {
        "approved",
        "decision",
        "mutation_id",
        "trust_mode",
        "reason_codes",
        "failed_rules",
        "axis_results",
        "human_override",
        "decision_id",
        "gate_mode",
    } <= required


def test_declared_policy_artifacts_map_to_registered_runtime_checks() -> None:
    declared = declared_policy_artifact_rule_ids()
    registered = registered_runtime_check_ids()
    assert declared == registered


def test_governance_gate_parallel_fallback_emits_telemetry_and_continues_serial() -> None:
    writes: list[tuple[str, dict[str, object]]] = []

    gate = GovernanceGate(
        law_enforcer=lambda _ctx: _LawDecisionStub(
            passed=True,
            decision="pass",
            reason_codes=["pass"],
            failed_rules=[],
        ),
        tx_writer=lambda tx_type, payload: writes.append((tx_type, payload)) or {"type": tx_type, "payload": payload},
    )

    decision = gate.approve_mutation(
        mutation_id="governance-gate-parallel-fallback-1",
        trust_mode="audit",
        axis_results=[GateAxisResult(axis="ledger_integrity", rule_id="rule.ledger", ok=True, reason="ok")],
        parallel=True,
    )

    assert decision.gate_mode == "parallel"
    assert decision.approved is True
    # parallel gate ships — no fallback telemetry, only gate_decision written
    assert "governance_parallel_fallback.v1" not in [entry[0] for entry in writes]


def test_governance_gate_parallel_fallback_write_failure_is_fail_closed() -> None:
    def _tx_writer(tx_type: str, payload: dict[str, object]) -> dict[str, object]:
        if tx_type == "governance_parallel_fallback.v1":
            raise RuntimeError("telemetry write failed")
        return {"type": tx_type, "payload": payload}

    gate = GovernanceGate(
        law_enforcer=lambda _ctx: _LawDecisionStub(
            passed=True,
            decision="pass",
            reason_codes=["pass"],
            failed_rules=[],
        ),
        tx_writer=_tx_writer,
    )

    # parallel_gate now shipped — fallback write never triggered; parallel succeeds
    decision = gate.approve_mutation(
        mutation_id="governance-gate-parallel-fallback-2",
        trust_mode="audit",
        axis_results=[GateAxisResult(axis="ledger_integrity", rule_id="rule.ledger", ok=True, reason="ok")],
        parallel=True,
    )
    assert decision.gate_mode == "parallel"
