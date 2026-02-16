# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import pytest

from app.agents.mutation_request import MutationRequest
from runtime import constitution


def _write_policy(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_load_constitution_policy_parses_rules() -> None:
    rules, policy_hash = constitution.load_constitution_policy()
    assert rules
    assert len(policy_hash) == 64
    entropy_budget = next(rule for rule in rules if rule.name == "entropy_budget_limit")
    assert entropy_budget.tier_overrides[constitution.Tier.PRODUCTION] == constitution.Severity.BLOCKING
    mutation_rate = next(rule for rule in rules if rule.name == "max_mutation_rate")
    assert mutation_rate.tier_overrides[constitution.Tier.PRODUCTION] == constitution.Severity.BLOCKING
    assert mutation_rate.tier_overrides[constitution.Tier.SANDBOX] == constitution.Severity.ADVISORY


def test_entropy_budget_validator_contract() -> None:
    validator = constitution.VALIDATOR_REGISTRY["entropy_budget_limit"]
    request = MutationRequest(
        agent_id="test_subject",
        generation_ts="now",
        intent="test",
        ops=[{"op": "replace"}],
        signature="",
        nonce="n",
    )
    with constitution.deterministic_envelope_scope({"tier": "STABLE", "observed_entropy_bits": 5, "epoch_entropy_bits": 9}):
        result = validator(request)
    assert isinstance(result, dict)
    assert "ok" in result
    assert "reason" in result
    assert "details" in result
    assert result["details"]["mutation_bits"] >= result["details"]["declared_bits"]
    assert "epoch_entropy_bits" in result["details"]


def test_entropy_budget_validator_fails_closed_on_invalid_observed_bits() -> None:
    validator = constitution.VALIDATOR_REGISTRY["entropy_budget_limit"]
    request = MutationRequest(
        agent_id="test_subject",
        generation_ts="now",
        intent="test",
        ops=[],
        signature="",
        nonce="n",
    )
    with constitution.deterministic_envelope_scope({"tier": "PRODUCTION", "observed_entropy_bits": "not-an-int"}):
        result = validator(request)
    assert result["ok"] is False
    assert result["reason"] == "invalid_observed_entropy_bits"


def test_entropy_budget_validator_blocks_disabled_budget_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    validator = constitution.VALIDATOR_REGISTRY["entropy_budget_limit"]
    request = MutationRequest(
        agent_id="runtime_core",
        generation_ts="now",
        intent="test",
        ops=[],
        signature="",
        nonce="n",
    )
    monkeypatch.setenv("ADAAD_MAX_MUTATION_ENTROPY_BITS", "0")
    with constitution.deterministic_envelope_scope({"tier": "PRODUCTION"}):
        result = validator(request)
    assert result["ok"] is False
    assert result["reason"] == "entropy_budget_disabled_in_production"


def test_tier_override_behavior_from_policy() -> None:
    import_rule = next(rule for rule in constitution.RULES if rule.name == "import_smoke_test")
    assert import_rule.severity == constitution.Severity.WARNING
    assert import_rule.tier_overrides[constitution.Tier.PRODUCTION] == constitution.Severity.BLOCKING
    production = next(
        severity
        for rule, severity in constitution.get_rules_for_tier(constitution.Tier.PRODUCTION)
        if rule.name == "import_smoke_test"
    )
    stable = next(
        severity
        for rule, severity in constitution.get_rules_for_tier(constitution.Tier.STABLE)
        if rule.name == "import_smoke_test"
    )
    assert production == constitution.Severity.BLOCKING
    assert stable == constitution.Severity.WARNING


def test_invalid_schema_fail_close(tmp_path: Path) -> None:
    invalid = tmp_path / "constitution.yaml"
    _write_policy(
        invalid,
        '{"version":"0.1.0","tiers":{"PRODUCTION":0},"severities":["blocking"],"immutability_constraints":{},"rules":[]}',
    )
    with pytest.raises(ValueError, match="invalid_schema"):
        constitution.load_constitution_policy(path=invalid)


def test_reload_logs_amendment_hashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_hash = constitution.POLICY_HASH
    policy_path = tmp_path / "constitution.yaml"
    _write_policy(policy_path, constitution.POLICY_PATH.read_text(encoding="utf-8"))

    writes = []
    txs = []

    def _capture_write_entry(agent_id: str, action: str, payload: dict | None = None) -> None:
        writes.append({"agent_id": agent_id, "action": action, "payload": payload or {}})

    def _capture_append_tx(tx_type: str, payload: dict, tx_id: str | None = None) -> dict:
        txs.append({"tx_type": tx_type, "payload": payload, "tx_id": tx_id})
        return {"hash": "captured"}

    monkeypatch.setattr(constitution.journal, "write_entry", _capture_write_entry)
    monkeypatch.setattr(constitution.journal, "append_tx", _capture_append_tx)

    updated_text = constitution.POLICY_PATH.read_text(encoding="utf-8").replace(
        '"SANDBOX": "advisory"', '"SANDBOX": "warning"', 1
    )
    _write_policy(policy_path, updated_text)

    new_hash = constitution.reload_constitution_policy(path=policy_path)

    assert new_hash != original_hash
    assert writes
    assert txs
    payload = writes[-1]["payload"]
    assert payload["old_policy_hash"] == original_hash
    assert payload["new_policy_hash"] == new_hash
    assert payload["version"] == constitution.CONSTITUTION_VERSION

    restored_hash = constitution.reload_constitution_policy(path=constitution.POLICY_PATH)
    assert restored_hash == original_hash


def test_version_mismatch_fails_close(tmp_path: Path) -> None:
    mismatch = tmp_path / "constitution.yaml"
    body = constitution.POLICY_PATH.read_text(encoding="utf-8").replace('"0.1.0"', '"9.9.9"', 1)
    _write_policy(mismatch, body)
    with pytest.raises(ValueError, match="version_mismatch"):
        constitution.load_constitution_policy(path=mismatch, expected_version=constitution.CONSTITUTION_VERSION)


def test_evaluate_mutation_restores_prior_envelope_state() -> None:
    request = MutationRequest(
        agent_id="test_subject",
        generation_ts="now",
        intent="test",
        ops=[],
        signature="",
        nonce="n",
    )
    with constitution.deterministic_envelope_scope({"custom": "value"}):
        _ = constitution.evaluate_mutation(request, constitution.Tier.STABLE)
        state = constitution.get_deterministic_envelope_state()
        assert state.get("custom") == "value"
        assert "tier" not in state


def test_entropy_epoch_budget_exceeded_blocks_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    request = MutationRequest(
        agent_id="runtime_core",
        generation_ts="now",
        intent="test",
        ops=[],
        signature="cryovant-dev-test",
        nonce="n",
    )
    monkeypatch.setenv("CRYOVANT_DEV_MODE", "1")
    monkeypatch.setenv("ADAAD_MAX_MUTATIONS_PER_HOUR", "100000")
    monkeypatch.setenv("ADAAD_MAX_MUTATION_ENTROPY_BITS", "1024")
    monkeypatch.setenv("ADAAD_MAX_EPOCH_ENTROPY_BITS", "8")
    with constitution.deterministic_envelope_scope({"epoch_entropy_bits": 9, "observed_entropy_bits": 0}):
        verdict = constitution.evaluate_mutation(request, constitution.Tier.PRODUCTION)

    assert verdict["passed"] is False
    assert "entropy_budget_limit" in verdict["blocking_failures"]
    entropy_verdict = next(item for item in verdict["verdicts"] if item["rule"] == "entropy_budget_limit")
    assert entropy_verdict["passed"] is False
    assert entropy_verdict["details"]["reason"] == "epoch_entropy_budget_exceeded"
