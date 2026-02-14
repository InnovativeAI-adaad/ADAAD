# SPDX-License-Identifier: Apache-2.0

from concurrent.futures import ThreadPoolExecutor
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


def test_policy_validator_parallel_validate_has_no_cross_talk() -> None:
    valid_policy = Path("runtime/governance/constitution.yaml").read_text(encoding="utf-8")
    payloads = [valid_policy if i % 2 == 0 else "{}" for i in range(100)]

    validator = PolicyValidator()
    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(validator.validate, payloads))

    for payload, result in zip(payloads, results, strict=True):
        expected_valid = payload == valid_policy
        assert result.valid is expected_valid
        if expected_valid:
            assert result.errors == []
        else:
            assert result.errors
