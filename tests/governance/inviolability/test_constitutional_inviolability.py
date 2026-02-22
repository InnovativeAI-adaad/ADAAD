# SPDX-License-Identifier: Apache-2.0
"""Constitutional inviolability acceptance tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.agents.mutation_request import MutationRequest, MutationTarget
from runtime.evolution.governor import EvolutionGovernor
from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.runtime import EvolutionRuntime
from runtime.governance.foundation import SeededDeterminismProvider, SystemDeterminismProvider, require_replay_safe_provider
from runtime.governance.policy_lifecycle import PolicyLifecycleError, apply_transition
from runtime.mutation_lifecycle import LifecycleTransitionError, MutationLifecycleContext, transition


@dataclass(frozen=True)
class _Impact:
    total: float


def _mutation_request(*, authority_level: str = "low-impact") -> MutationRequest:
    return MutationRequest(
        agent_id="test_subject",
        generation_ts="2026-01-01T00:00:00Z",
        intent="governance-inviolability",
        ops=[{"op": "replace", "path": "runtime/constitution.py", "value": "harden"}],
        signature="cryovant-dev-test",
        nonce="nonce-1",
        targets=[
            MutationTarget(
                agent_id="test_subject",
                path="runtime/constitution.py",
                target_type="file",
                ops=[{"op": "replace", "path": "runtime/constitution.py", "value": "harden"}],
            )
        ],
        authority_level=authority_level,
    )


def test_invariant_mutation_execution_requires_constitutional_guard_path_with_positive_transition(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal_events: list[dict] = []
    tx_events: list[dict] = []
    monkeypatch.setattr(
        "runtime.mutation_lifecycle.journal.write_entry",
        lambda agent_id, action, payload=None: journal_events.append(
            {"agent_id": agent_id, "action": action, "payload": payload or {}}
        ),
    )
    monkeypatch.setattr(
        "runtime.mutation_lifecycle.journal.append_tx",
        lambda tx_type, payload, tx_id=None: tx_events.append(
            {"tx_type": tx_type, "payload": payload, "tx_id": tx_id}
        ),
    )

    context = MutationLifecycleContext(
        mutation_id="mut-pass-1",
        agent_id="test_subject",
        epoch_id="epoch-1",
        signature="cryovant-static-allow",
        cert_refs={"certificate_digest": "sha256:" + ("a" * 64)},
        fitness_score=0.9,
        fitness_threshold=0.5,
        founders_law_result=(True, []),
        trust_mode="prod",
        state_dir=tmp_path,
    )
    new_state = transition("certified", "executing", context)

    assert new_state == "executing"
    assert journal_events[-1]["action"] == "mutation_lifecycle_transition"
    assert journal_events[-1]["payload"]["guard_report"]["ok"] is True
    assert tx_events[-1]["tx_type"] == "mutation_lifecycle_transition"
    assert {"from_state", "to_state", "guard_report"}.issubset(tx_events[-1]["payload"])


def test_invariant_mutation_execution_rejects_adversarial_bypass_without_explicit_certification(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal_events: list[dict] = []
    tx_events: list[dict] = []
    monkeypatch.setattr(
        "runtime.mutation_lifecycle.journal.write_entry",
        lambda agent_id, action, payload=None: journal_events.append(
            {"agent_id": agent_id, "action": action, "payload": payload or {}}
        ),
    )
    monkeypatch.setattr(
        "runtime.mutation_lifecycle.journal.append_tx",
        lambda tx_type, payload, tx_id=None: tx_events.append(
            {"tx_type": tx_type, "payload": payload, "tx_id": tx_id}
        ),
    )

    context = MutationLifecycleContext(
        mutation_id="mut-fail-1",
        agent_id="test_subject",
        epoch_id="epoch-1",
        signature="cryovant-static-allow",
        cert_refs={},
        fitness_score=0.9,
        founders_law_result=(True, []),
        trust_mode="prod",
        state_dir=tmp_path,
    )

    with pytest.raises(LifecycleTransitionError, match="guard_failed"):
        transition("certified", "executing", context)

    assert journal_events[-1]["action"] == "mutation_lifecycle_rejected"
    assert journal_events[-1]["payload"]["guard_report"]["cert_reference_gate"]["ok"] is False
    assert tx_events[-1]["tx_type"] == "mutation_lifecycle_rejected"
    assert {"from_state", "to_state", "guard_report"}.issubset(tx_events[-1]["payload"])


def test_invariant_replay_divergence_fail_closes_strict_mode(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch_path = tmp_path / "lineage_strict.jsonl"
    import runtime.evolution.lineage_v2 as lineage_v2

    monkeypatch.setattr(lineage_v2, "LEDGER_V2_PATH", monkeypatch_path)
    runtime = EvolutionRuntime(provider=SeededDeterminismProvider("strict-seed"))
    result = runtime.replay_preflight("strict", epoch_id="epoch-strict")

    assert result["decision"] == "fail_closed"
    assert result["has_divergence"] is True
    assert runtime.governor.fail_closed is True
    assert runtime.governor.fail_closed_reason == "replay_divergence"
    replay_events = [
        entry for entry in runtime.ledger.read_epoch("epoch-strict") if entry.get("type") == "ReplayVerificationEvent"
    ]
    assert replay_events
    assert {"decision", "replay_passed", "epoch_digest", "replay_digest"}.issubset(replay_events[-1]["payload"])


def test_invariant_replay_divergence_audit_mode_is_observable_but_not_fail_closed(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch_path = tmp_path / "lineage_audit.jsonl"
    import runtime.evolution.lineage_v2 as lineage_v2

    monkeypatch.setattr(lineage_v2, "LEDGER_V2_PATH", monkeypatch_path)
    runtime = EvolutionRuntime(provider=SeededDeterminismProvider("audit-seed"))
    result = runtime.replay_preflight("audit", epoch_id="epoch-audit")

    assert result["decision"] == "continue"
    assert result["has_divergence"] is True
    assert runtime.governor.fail_closed is False
    replay_events = [
        entry for entry in runtime.ledger.read_epoch("epoch-audit") if entry.get("type") == "ReplayVerificationEvent"
    ]
    assert replay_events
    assert replay_events[-1]["payload"]["decision"] in {"diverge", "match"}


def test_invariant_nondeterministic_provider_rejected_on_strict_and_audit_paths() -> None:
    provider = SystemDeterminismProvider()

    with pytest.raises(RuntimeError, match="strict_replay_requires_deterministic_provider"):
        require_replay_safe_provider(provider, replay_mode="strict")
    with pytest.raises(RuntimeError, match="audit_tier_requires_deterministic_provider"):
        require_replay_safe_provider(provider, recovery_tier="audit")


def test_invariant_deterministic_provider_allowed_on_strict_and_audit_paths() -> None:
    provider = SeededDeterminismProvider("inviolability-seed")

    require_replay_safe_provider(provider, replay_mode="strict")
    require_replay_safe_provider(provider, recovery_tier="audit")


def test_invariant_policy_authority_expansion_requires_explicit_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    tx_events: list[dict] = []
    monkeypatch.setattr(
        "runtime.governance.policy_lifecycle.append_tx",
        lambda tx_type, payload, tx_id=None: tx_events.append(
            {"tx_type": tx_type, "payload": payload, "tx_id": tx_id}
        ) or {"hash": "captured"},
    )

    transition_result = apply_transition(
        artifact_digest="sha256:" + ("1" * 64),
        from_state="authoring",
        to_state="review-approved",
        proof={
            "artifact_digest": "sha256:" + ("1" * 64),
            "previous_transition_hash": "sha256:" + ("2" * 64),
            "evidence": {"approvals": ["security-review"]},
        },
    )

    assert transition_result.to_state == "review-approved"
    assert tx_events[-1]["tx_type"] == "policy_lifecycle_transition"
    assert {"artifact_digest", "from_state", "to_state", "proof", "transition_hash"}.issubset(tx_events[-1]["payload"])


def test_invariant_policy_authority_cannot_expand_silently_via_transition_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    tx_events: list[dict] = []
    monkeypatch.setattr(
        "runtime.governance.policy_lifecycle.append_tx",
        lambda tx_type, payload, tx_id=None: tx_events.append(
            {"tx_type": tx_type, "payload": payload, "tx_id": tx_id}
        ) or {"hash": "captured"},
    )

    with pytest.raises(PolicyLifecycleError, match="invalid transition"):
        apply_transition(
            artifact_digest="sha256:" + ("1" * 64),
            from_state="authoring",
            to_state="signed",
            proof={
                "artifact_digest": "sha256:" + ("1" * 64),
                "previous_transition_hash": "sha256:" + ("2" * 64),
                "evidence": {"approvals": ["attempted-bypass"]},
            },
        )

    assert tx_events == []


def test_invariant_governance_self_mutation_high_risk_requires_explicit_authority_path(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAAD_ENV", "dev")
    monkeypatch.setenv("CRYOVANT_DEV_MODE", "1")

    ledger = LineageLedgerV2(tmp_path / "lineage_self_mutation_fail.jsonl")
    governor = EvolutionGovernor(
        ledger=ledger,
        provider=SeededDeterminismProvider("authority-seed"),
    )
    governor.mark_epoch_start("epoch-authority")
    governor.impact_scorer.score = lambda _request: _Impact(total=0.7)  # type: ignore[method-assign]

    decision = governor.validate_bundle(_mutation_request(authority_level="low-impact"), epoch_id="epoch-authority")

    assert decision.accepted is False
    assert decision.reason == "authority_level_exceeded"
    events = [entry for entry in ledger.read_epoch("epoch-authority") if entry.get("type") == "GovernanceDecisionEvent"]
    assert events
    assert events[-1]["payload"]["reason"] == "authority_level_exceeded"
    assert {"accepted", "reason", "impact_score", "epoch_id"}.issubset(events[-1]["payload"])


def test_invariant_governance_self_mutation_accepts_explicit_high_risk_authority_path(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAAD_ENV", "dev")
    monkeypatch.setenv("CRYOVANT_DEV_MODE", "1")

    ledger = LineageLedgerV2(tmp_path / "lineage_self_mutation_pass.jsonl")
    governor = EvolutionGovernor(
        ledger=ledger,
        provider=SeededDeterminismProvider("authority-seed-pass"),
    )
    governor.mark_epoch_start("epoch-authority-pass")
    governor.impact_scorer.score = lambda _request: _Impact(total=0.7)  # type: ignore[method-assign]

    decision = governor.validate_bundle(_mutation_request(authority_level="high-impact"), epoch_id="epoch-authority-pass")

    assert decision.accepted is True
    assert decision.reason == "accepted"
    assert decision.certificate
    assert "authority_signatures" in decision.certificate
