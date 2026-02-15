# SPDX-License-Identifier: Apache-2.0

import json

import pytest

from runtime.governance.policy_artifact import GovernancePolicyError, load_governance_policy


def test_load_governance_policy_valid(tmp_path) -> None:
    policy_path = tmp_path / "governance_policy_v1.json"
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": "governance_policy_v1",
                "model": {"name": "governance_health", "version": "v1.2.3"},
                "determinism_window": 180,
                "mutation_rate_window_sec": 3600,
                "thresholds": {"determinism_pass": 0.97, "determinism_warn": 0.9},
            }
        ),
        encoding="utf-8",
    )

    policy = load_governance_policy(policy_path)

    assert policy.schema_version == "governance_policy_v1"
    assert policy.model.version == "v1.2.3"
    assert policy.determinism_window == 180
    assert policy.thresholds.determinism_pass == 0.97
    assert policy.fingerprint.startswith("sha256:")


def test_load_governance_policy_missing_required_field(tmp_path) -> None:
    policy_path = tmp_path / "broken_policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": "governance_policy_v1",
                "model": {"name": "governance_health", "version": "v1.0.0"},
                "determinism_window": 200,
                "mutation_rate_window_sec": 3600,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(GovernancePolicyError, match="thresholds must be an object"):
        load_governance_policy(policy_path)


def test_load_governance_policy_rejects_invalid_threshold_order(tmp_path) -> None:
    policy_path = tmp_path / "broken_thresholds.json"
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": "governance_policy_v1",
                "model": {"name": "governance_health", "version": "v1.0.0"},
                "determinism_window": 200,
                "mutation_rate_window_sec": 3600,
                "thresholds": {"determinism_pass": 0.9, "determinism_warn": 0.95},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(GovernancePolicyError, match="determinism_warn"):
        load_governance_policy(policy_path)
