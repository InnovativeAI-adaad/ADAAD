# SPDX-License-Identifier: Apache-2.0

# ADAAD-LANE: constitutional-inviolability

from pathlib import Path
import pytest
from adaad.agents.mutation_request import MutationRequest, MutationTarget
from runtime import constitution
pytestmark = pytest.mark.governance_gate

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
    assert mutation_rate.applicability["name"] == "max_mutation_rate"

    advisory_rule_names = {"deployment_authority_tier", "revenue_credit_floor", "reviewer_calibration"}
    advisory_rules = [rule for rule in rules if rule.name in advisory_rule_names]
    assert {rule.name for rule in advisory_rules} == advisory_rule_names
    assert all(rule.enabled for rule in advisory_rules)
    assert all(rule.severity == constitution.Severity.ADVISORY for rule in advisory_rules)
    assert all(rule.tier_overrides == {} for rule in advisory_rules)

def test_phase63_scaffold_rules_load_as_advisory() -> None:
    rules, _ = constitution.load_constitution_policy()
    scaffold_rule_names = {
        "phase63_ast_safe_scaffold",
        "phase63_ast_import_scaffold",
        "phase63_ast_complexity_scaffold",
        "phase63_semantic_integrity_scaffold",
        "phase63_exception_scope_scaffold",
    }
    scaffold_rules = [rule for rule in rules if rule.name in scaffold_rule_names]
    assert {rule.name for rule in scaffold_rules} == scaffold_rule_names
    assert all(rule.enabled for rule in scaffold_rules)
    assert all(rule.severity == constitution.Severity.ADVISORY for rule in scaffold_rules)
    assert all(rule.tier_overrides == {} for rule in scaffold_rules)


def test_phase63_scaffold_validators_are_discovered_via_policy_load() -> None:
    rules, _ = constitution.load_constitution_policy()
    validators_by_name = {
        rule.name: rule.validator.__name__
        for rule in rules
        if rule.name.startswith("phase63_") and rule.name.endswith("_scaffold")
    }

    assert validators_by_name == {
        "phase63_ast_safe_scaffold": "_validate_phase63_ast_safe_scaffold",
        "phase63_ast_import_scaffold": "_validate_phase63_ast_import_scaffold",
        "phase63_ast_complexity_scaffold": "_validate_phase63_ast_complexity_scaffold",
        "phase63_semantic_integrity_scaffold": "_validate_phase63_semantic_integrity_scaffold",
        "phase63_exception_scope_scaffold": "_validate_phase63_exception_scope_scaffold",
    }

def test_entropy_budget_validator_fails_closed_on_invalid_observed_bits() -> None:
    validator = constitution.VALIDATOR_REGISTRY["entropy_budget_limit"]
    request = MutationRequest(
        agent_id="test_subject",
        generation_ts="now",
        intent="test",
        ops=[{"op": "replace", "path": "runtime/constitution.py", "value": "x"}],
        signature="cryovant-dev-test",
        nonce="n",
        targets=[MutationTarget(agent_id="test_subject", path="runtime/constitution.py", target_type="file", ops=[])],
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
def test_advisory_rule_failures_do_not_block_evaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    request = MutationRequest(
        agent_id="test_subject",
        generation_ts="now",
        intent="test",
        ops=[],
        signature="cryovant-dev-test",
        nonce="n",
    )

    original_validator = constitution.VALIDATOR_REGISTRY["deployment_authority_tier"]
    monkeypatch.setitem(
        constitution.VALIDATOR_REGISTRY,
        "deployment_authority_tier",
        lambda _request: {"ok": False, "reason": "simulated_advisory_failure", "details": {}},
    )
    constitution.reload_constitution_policy(path=constitution.POLICY_PATH)
    try:
        verdict = constitution.evaluate_mutation(request, constitution.Tier.STABLE)
        assert "deployment_authority_tier" not in verdict["blocking_failures"]
        assert "deployment_authority_tier" not in verdict["warnings"]
        advisory_row = next(item for item in verdict["verdicts"] if item["rule"] == "deployment_authority_tier")
        assert advisory_row["passed"] is False
        assert advisory_row["severity"] == constitution.Severity.ADVISORY.value
    finally:
        monkeypatch.setitem(constitution.VALIDATOR_REGISTRY, "deployment_authority_tier", original_validator)
        constitution.reload_constitution_policy(path=constitution.POLICY_PATH)
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
def test_load_policy_document_parses_yaml_content(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.yaml"
    _write_policy(policy_path, "version: 0.3.0\nrules: []\n")

    policy, policy_hash = constitution._load_policy_document(policy_path)

    assert policy["version"] == "0.3.0"
    assert policy["rules"] == []
    assert len(policy_hash) == 64
def test_load_policy_document_parses_json_in_yaml_extension(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.yaml"
    _write_policy(policy_path, '{"version":"0.3.0","rules":[]}')

    policy, _ = constitution._load_policy_document(policy_path)

    assert policy["version"] == "0.3.0"
    assert policy["rules"] == []
def test_load_policy_document_maps_malformed_json_or_yaml_to_value_error(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.yaml"
    _write_policy(policy_path, "version: [unterminated")

    with pytest.raises(ValueError, match="constitution_policy_invalid_json"):
        constitution._load_policy_document(policy_path)
def test_invalid_schema_fail_close(tmp_path: Path) -> None:
    invalid = tmp_path / "constitution.yaml"
    _write_policy(
        invalid,
        '{"version":"0.3.0","tiers":{"PRODUCTION":0},"severities":["blocking"],"immutability_constraints":{},"rules":[]}',
    )
    with pytest.raises(ValueError, match="invalid_schema"):
        constitution.load_constitution_policy(path=invalid)
def test_version_mismatch_fails_close(tmp_path: Path) -> None:
    mismatch = tmp_path / "constitution.yaml"
    body = constitution.POLICY_PATH.read_text(encoding="utf-8").replace('"version": "1.0.0"', '"version": "9.9.9"', 1)
    _write_policy(mismatch, body)
    with pytest.raises(ValueError, match="version_mismatch"):
        constitution.load_constitution_policy(path=mismatch, expected_version=constitution.CONSTITUTION_VERSION)
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
def test_resource_bounds_validator_uses_env_overrides_and_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    validator = constitution.VALIDATOR_REGISTRY["resource_bounds"]
    request = MutationRequest(
        agent_id="test_subject",
        generation_ts="now",
        intent="test",
        ops=[],
        signature="",
        nonce="n",
    )
    monkeypatch.setenv("ADAAD_RESOURCE_MEMORY_MB", "100")
    monkeypatch.setenv("ADAAD_RESOURCE_CPU_SECONDS", "5")
    monkeypatch.setenv("ADAAD_RESOURCE_WALL_SECONDS", "10")

    with constitution.deterministic_envelope_scope(
        {
            "agent_id": request.agent_id,
            "epoch_id": "epoch-1",
            "platform_telemetry": {"memory_mb": 256.0, "cpu_percent": 50.0, "battery_percent": 90.0, "storage_mb": 2048.0},
            "resource_measurements": {"peak_rss_mb": 128.0, "cpu_seconds": 1.0, "wall_seconds": 2.0},
        }
    ):
        result = validator(request)

    assert result["ok"] is False
    assert result["reason"] == "resource_bounds_exceeded"
    assert "memory" in result["details"]["violations"]
def test_resource_bounds_policy_precedes_env_when_overrides_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    validator = constitution.VALIDATOR_REGISTRY["resource_bounds"]
    request = MutationRequest(
        agent_id="test_subject",
        generation_ts="now",
        intent="test",
        ops=[],
        signature="",
        nonce="n",
    )
    monkeypatch.setenv("ADAAD_RESOURCE_MEMORY_MB", "1")
    original_policy = dict(constitution._POLICY_DOCUMENT)
    patched_policy = dict(original_policy)
    patched_policy["resource_bounds_policy"] = {
        "policy_version": "1.0.0",
        "limits": {"memory_mb": 2048, "cpu_seconds": 30, "wall_seconds": 60},
        "allow_env_overrides": [],
    }
    monkeypatch.setattr(constitution, "_POLICY_DOCUMENT", patched_policy)

    with constitution.deterministic_envelope_scope({"resource_measurements": {"peak_rss_mb": 128.0}}):
        result = validator(request)

    assert result["ok"] is True
    assert result["details"]["bounds_policy_version"] == "1.0.0"
def test_resource_bounds_validator_rejects_invalid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    validator = constitution.VALIDATOR_REGISTRY["resource_bounds"]
    request = MutationRequest(
        agent_id="test_subject",
        generation_ts="now",
        intent="test",
        ops=[],
        signature="",
        nonce="n",
    )
    monkeypatch.setenv("ADAAD_RESOURCE_MEMORY_MB", "bad")
    with constitution.deterministic_envelope_scope({"resource_measurements": {"peak_rss_mb": 1.0}}):
        result = validator(request)
    assert result["ok"] is False
    assert result["reason"] == "invalid_resource_memory_bound"
def test_evaluation_emits_governance_envelope_digest() -> None:
    request = MutationRequest(
        agent_id="test_subject",
        generation_ts="now",
        intent="test",
        ops=[],
        signature="",
        nonce="n",
    )
    first = constitution.evaluate_mutation(request, constitution.Tier.SANDBOX)
    second = constitution.evaluate_mutation(request, constitution.Tier.SANDBOX)

    assert "governance_envelope" in first
    assert first["governance_envelope"]["digest"]
    assert first["governance_envelope"]["digest"] == second["governance_envelope"]["digest"]
def test_rule_dependency_ordering_places_lineage_before_mutation_rate() -> None:
    request = MutationRequest(
        agent_id="test_subject",
        generation_ts="now",
        intent="test",
        ops=[],
        signature="",
        nonce="n",
    )
    verdict = constitution.evaluate_mutation(request, constitution.Tier.SANDBOX)
    names = [item["rule"] for item in verdict["verdicts"]]
    assert names.index("lineage_continuity") < names.index("max_mutation_rate")
def test_coverage_not_configured_is_non_blocking() -> None:
    validator = constitution.VALIDATOR_REGISTRY["test_coverage_maintained"]
    request = MutationRequest(
        agent_id="test_subject",
        generation_ts="now",
        intent="test",
        ops=[],
        signature="",
        nonce="n",
    )
    with constitution.deterministic_envelope_scope({}):
        result = validator(request)
    assert result["ok"] is True
    assert result["reason"] == "coverage_artifact_not_configured"
def test_validator_provenance_handles_source_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    validator = constitution.VALIDATOR_REGISTRY["lineage_continuity"]

    def _raise(_obj):
        raise OSError("source unavailable")

    monkeypatch.setattr(constitution.inspect, "getsource", _raise)
    constitution._validator_source_hash.cache_clear()
    row = constitution._validator_provenance(next(rule for rule in constitution.RULES if rule.validator is validator))
    assert row["validator_source_hash"] == "source_unavailable"
    constitution._validator_source_hash.cache_clear()
def test_governance_drift_blocks_production(monkeypatch: pytest.MonkeyPatch) -> None:
    request = MutationRequest(
        agent_id="runtime_core",
        generation_ts="now",
        intent="test",
        ops=[],
        signature="",
        nonce="n",
    )
    monkeypatch.setattr(constitution, "_current_governance_fingerprint", lambda: "drifted")
    monkeypatch.setattr(constitution, "_BASE_GOVERNANCE_FINGERPRINT", "baseline")
    verdict = constitution.evaluate_mutation(request, constitution.Tier.PRODUCTION)
    assert verdict["governance_drift_detected"] is True
    assert "governance_drift_detected" in verdict["blocking_failures"]
def test_effective_limit_uses_strictest_domain_ceiling_for_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    request = MutationRequest(
        agent_id="test_subject",
        generation_ts="now",
        intent="test",
        ops=[],
        signature="",
        nonce="n",
        targets=[
            MutationTarget(agent_id="test_subject", path="docs/guide.md", target_type="file", ops=[]),
            MutationTarget(agent_id="test_subject", path="security/policy.py", target_type="file", ops=[]),
        ],
    )

    monkeypatch.setenv("ADAAD_MAX_MUTATION_RATE", "10")
    monkeypatch.setenv("CRYOVANT_DEV_MODE", "1")
    monkeypatch.setattr(constitution, "_deterministic_mutation_count", lambda window_sec, epoch_id: {
        "window_sec": window_sec,
        "window_start_ts": 0.0,
        "window_end_ts": 0.0,
        "count": 5,
        "rate_per_hour": 5.0,
        "event_types": [],
        "entries_considered": 0,
        "entries_scoped": 0,
        "scope": {"epoch_id": "*"},
        "source": "test",
    })

    with constitution.deterministic_envelope_scope(
        {
            "tier": constitution.Tier.PRODUCTION.name,
            "domain_classification": constitution._classify_request_domains(request),
        }
    ):
        result = constitution._validate_mutation_rate(request)

    assert result["ok"] is False
    assert result["details"]["tier_limit"] == 10.0
    assert result["details"]["domain_limit"] == 4.0
    assert result["details"]["applied_ceiling"] == 4.0
    assert result["details"]["resolved_domain"] == "security"
def test_enabled_policy_rules_have_validator_registry_and_version_entries() -> None:
    enabled_rules = [rule for rule in constitution.RULES if rule.enabled]
    assert enabled_rules

    for rule in enabled_rules:
        validator_name = getattr(rule.validator, "__name__", "")
        assert rule.name in constitution.VALIDATOR_REGISTRY
        assert callable(rule.validator)
        assert validator_name in constitution.VALIDATOR_VERSIONS
def test_severity_escalation_framework_supports_warning_and_blocking() -> None:
    request = MutationRequest(
        agent_id="test_subject",
        generation_ts="now",
        intent="test",
        ops=[],
        signature="cryovant-dev-test",
        nonce="n",
    )

    with constitution.deterministic_envelope_scope(
        {
            "severity_escalations": {
                "deployment_authority_tier": "warning",
                "reviewer_calibration": "blocking",
            }
        }
    ):
        verdict = constitution.evaluate_mutation(request, constitution.Tier.STABLE)

    deployment_row = next(item for item in verdict["verdicts"] if item["rule"] == "deployment_authority_tier")
    reviewer_row = next(item for item in verdict["verdicts"] if item["rule"] == "reviewer_calibration")

    assert deployment_row["severity"] == constitution.Severity.WARNING.value
    assert deployment_row["base_severity"] == constitution.Severity.ADVISORY.value
    assert reviewer_row["severity"] == constitution.Severity.BLOCKING.value
    assert reviewer_row["base_severity"] == constitution.Severity.ADVISORY.value
def test_severity_escalation_does_not_allow_deescalation() -> None:
    request = MutationRequest(
        agent_id="test_subject",
        generation_ts="now",
        intent="test",
        ops=[],
        signature="cryovant-dev-test",
        nonce="n",
    )

    with constitution.deterministic_envelope_scope({"severity_escalations": {"resource_bounds": "advisory"}}):
        verdict = constitution.evaluate_mutation(request, constitution.Tier.STABLE)

    row = next(item for item in verdict["verdicts"] if item["rule"] == "resource_bounds")
    assert row["severity"] == constitution.Severity.BLOCKING.value
