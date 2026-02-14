# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy

import pytest

from runtime.evolution.scoring_algorithm import (
    RISK_WEIGHTS,
    SEVERITY_WEIGHTS,
    ScoringValidationError,
    compute_score,
)
from runtime.governance.foundation import SeededDeterminismProvider, sha256_prefixed_digest


def _sample() -> dict:
    return {
        "mutation_id": "mut-1",
        "epoch_id": "epoch-1",
        "constitution_hash": "sha256:" + ("a" * 64),
        "test_results": {"total": 10, "failed": 0},
        "static_analysis": {
            "issues": [
                {"rule_id": "R2", "severity": "LOW"},
                {"rule_id": "R1", "severity": "HIGH"},
            ]
        },
        "code_diff": {
            "loc_added": 5,
            "loc_deleted": 3,
            "files_touched": 1,
            "risk_tags": ["API", "SECURITY"],
        },
    }


def test_scoring_determinism_1000_iterations() -> None:
    provider = SeededDeterminismProvider(seed="score-seed")
    sample = _sample()
    seen = set()
    for _ in range(1000):
        result = compute_score(sample, provider=provider, replay_mode="strict")
        record_hash = sha256_prefixed_digest({k: v for k, v in result.items() if k != "timestamp"})
        seen.add((result["score"], result["input_hash"], record_hash))
    assert len(seen) == 1


def test_input_not_mutated() -> None:
    sample = _sample()
    before = copy.deepcopy(sample)
    compute_score(sample, provider=SeededDeterminismProvider(seed="immut"), replay_mode="strict")
    assert sample == before


def test_hard_limits_enforced() -> None:
    sample = _sample()
    sample["code_diff"]["loc_added"] = 200_000
    with pytest.raises(ScoringValidationError):
        compute_score(sample, provider=SeededDeterminismProvider(seed="limit"), replay_mode="strict")


def test_score_floor_non_negative() -> None:
    sample = _sample()
    sample["test_results"]["failed"] = 1
    sample["code_diff"]["loc_added"] = 50_000
    result = compute_score(sample, provider=SeededDeterminismProvider(seed="floor"), replay_mode="strict")
    assert result["score"] >= 0


def test_weight_tables_immutable() -> None:
    with pytest.raises(TypeError):
        SEVERITY_WEIGHTS["NEW"] = 1
    with pytest.raises(TypeError):
        RISK_WEIGHTS["NEW"] = 1
