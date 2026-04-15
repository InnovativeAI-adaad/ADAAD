# SPDX-License-Identifier: Apache-2.0
import json
import pytest
pytestmark = pytest.mark.regression_standard

from pathlib import Path
from unittest import mock

from runtime.mcp.proposal_validator import ProposalValidationError, validate_proposal


def _payload(**overrides):
    base = {
        "agent_id": "claude-proposal-agent",
        "generation_ts": "2026-01-01T00:00:00Z",
        "intent": "improve test coverage",
        "ops": [{"op": "replace", "path": "x", "value": "safe"}],
        "targets": [{"agent_id": "a", "path": "app/foo.py", "target_type": "file", "ops": []}],
        "signature": "sig",
        "nonce": "n",
        "authority_level": "auto-execute",
    }
    base.update(overrides)
    return base


@mock.patch("runtime.mcp.proposal_validator.evaluate_mutation", return_value={"passed": True, "verdicts": []})
def test_valid_proposal_passes(_eval):
    req, _ = validate_proposal(_payload())
    assert req.authority_level == "governor-review"


@mock.patch("runtime.mcp.proposal_validator.evaluate_mutation", return_value={"passed": True, "verdicts": []})
def test_authority_override_low_impact(_eval):
    req, _ = validate_proposal(_payload(authority_level="low-impact"))
    assert req.authority_level == "governor-review"


def test_tier0_requires_elevation():
    with pytest.raises(ProposalValidationError) as exc:
        validate_proposal(_payload(targets=[{"agent_id": "a", "path": "runtime/constitution.py", "target_type": "file", "ops": []}]))
    assert exc.value.status_code == 403
    assert exc.value.code == "tier0_escalation_required"


@mock.patch(
    "runtime.mcp.proposal_validator.evaluate_mutation",
    return_value={"passed": False, "verdicts": [{"severity": "blocking", "ok": False, "rule": "x"}]},
)
def test_blocking_constitution_verdict_rejected(_eval):
    with pytest.raises(ProposalValidationError) as exc:
        validate_proposal(_payload())
    assert exc.value.status_code == 422
    assert exc.value.code == "pre_check_failed"


def test_missing_required_field():
    payload = _payload()
    payload.pop("nonce")
    with pytest.raises(ProposalValidationError) as exc:
        validate_proposal(payload)
    assert exc.value.status_code == 400

@mock.patch("runtime.mcp.proposal_validator.evaluate_mutation", return_value={"passed": True, "verdicts": []})
def test_grok_agent_rejected_when_disabled(_eval, tmp_path, monkeypatch):
    profile_path = tmp_path / "governance_runtime_profile.lock.json"
    profile_path.write_text(
        json.dumps(
            {
                "version": 1,
                "dependency_lock": {"path": "requirements.server.txt", "sha256": "2b531ef1b5494577c3994abfc429dc78f5fbb3f4161b2b89c659cfd77ac72ad5"},
                "runtime_manifest": {
                    "governance_modes": ["strict"],
                    "deterministic_provider_required": True,
                    "mutable_filesystem": {"disable_env": "A", "allowlist_env": "B", "allowlist": ["reports"]},
                    "network": {"disable_env": "C", "allowlist_env": "D", "allowlist": ["127.0.0.1"]},
                },
                "agents": {"grok-integrator": {"enabled": False, "metadata": {"vault_file": "security/ledger/credentials/grok_pat.vault"}}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("runtime.mcp.proposal_validator.RUNTIME_PROFILE_PATH", profile_path)
    monkeypatch.setattr("runtime.mcp.proposal_validator.SCHEMA_PATH", Path(__file__).resolve().parents[2] / "schemas" / "llm_mutation_proposal.v1.json")

    with pytest.raises(ProposalValidationError) as exc:
        validate_proposal(_payload(agent_id="grok-integrator"))
    assert exc.value.code == "grok_disabled"


@mock.patch("runtime.mcp.proposal_validator.evaluate_mutation", return_value={"passed": True, "verdicts": []})
def test_grok_agent_rejected_when_enabled_without_vault(_eval, tmp_path, monkeypatch):
    profile_path = tmp_path / "governance_runtime_profile.lock.json"
    profile_path.write_text(
        json.dumps(
            {
                "version": 1,
                "dependency_lock": {"path": "requirements.server.txt", "sha256": "2b531ef1b5494577c3994abfc429dc78f5fbb3f4161b2b89c659cfd77ac72ad5"},
                "runtime_manifest": {
                    "governance_modes": ["strict"],
                    "deterministic_provider_required": True,
                    "mutable_filesystem": {"disable_env": "A", "allowlist_env": "B", "allowlist": ["reports"]},
                    "network": {"disable_env": "C", "allowlist_env": "D", "allowlist": ["127.0.0.1"]},
                },
                "agents": {"grok-integrator": {"enabled": True, "metadata": {"vault_file": "security/ledger/credentials/missing.vault"}}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("runtime.mcp.proposal_validator.RUNTIME_PROFILE_PATH", profile_path)
    monkeypatch.setattr("runtime.mcp.proposal_validator.SCHEMA_PATH", Path(__file__).resolve().parents[2] / "schemas" / "llm_mutation_proposal.v1.json")

    with pytest.raises(ProposalValidationError) as exc:
        validate_proposal(_payload(agent_id="grok-integrator"))
    assert exc.value.code == "grok_unbound"


@mock.patch("runtime.mcp.proposal_validator.evaluate_mutation", return_value={"passed": True, "verdicts": []})
def test_grok_agent_allowed_when_enabled_with_vault(_eval, tmp_path, monkeypatch):
    vault = tmp_path / "security" / "ledger" / "credentials" / "grok_pat.vault"
    vault.parent.mkdir(parents=True, exist_ok=True)
    vault.write_text("token", encoding="utf-8")

    profile_path = tmp_path / "governance_runtime_profile.lock.json"
    profile_path.write_text(
        json.dumps(
            {
                "version": 1,
                "dependency_lock": {"path": "requirements.server.txt", "sha256": "2b531ef1b5494577c3994abfc429dc78f5fbb3f4161b2b89c659cfd77ac72ad5"},
                "runtime_manifest": {
                    "governance_modes": ["strict"],
                    "deterministic_provider_required": True,
                    "mutable_filesystem": {"disable_env": "A", "allowlist_env": "B", "allowlist": ["reports"]},
                    "network": {"disable_env": "C", "allowlist_env": "D", "allowlist": ["127.0.0.1"]},
                },
                "agents": {
                    "grok-integrator": {
                        "enabled": True,
                        "metadata": {"vault_file": "security/ledger/credentials/grok_pat.vault"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("runtime.mcp.proposal_validator.RUNTIME_PROFILE_PATH", profile_path)
    monkeypatch.setattr("runtime.mcp.proposal_validator.SCHEMA_PATH", Path(__file__).resolve().parents[2] / "schemas" / "llm_mutation_proposal.v1.json")

    request, _ = validate_proposal(_payload(agent_id="grok-integrator"))
    assert request.authority_level == "governor-review"
