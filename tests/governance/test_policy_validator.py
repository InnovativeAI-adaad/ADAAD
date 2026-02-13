# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from runtime.governance.policy_validator import PolicyValidator


def test_policy_validator_accepts_valid_policy() -> None:
    policy_text = Path("runtime/governance/constitution.yaml").read_text(encoding="utf-8")
    result = PolicyValidator().validate(policy_text)
    assert result.valid


def test_policy_validator_rejects_invalid_policy() -> None:
    result = PolicyValidator().validate("{}")
    assert not result.valid
    assert result.errors
