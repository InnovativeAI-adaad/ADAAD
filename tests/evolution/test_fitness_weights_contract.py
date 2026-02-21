# SPDX-License-Identifier: Apache-2.0

import json

import pytest

from runtime.evolution.economic_fitness import EconomicFitnessEvaluator


def test_fitness_weights_config_matches_schema_contract() -> None:
    schema = json.loads(open("schemas/fitness_weights.schema.json", encoding="utf-8").read())
    config = json.loads(open("runtime/evolution/config/fitness_weights.json", encoding="utf-8").read())

    required = set(schema["required"])
    assert required.issubset(config.keys())

    required_weight_keys = set(schema["properties"]["weights"]["required"])
    config_weight_keys = set(config["weights"].keys())
    assert config_weight_keys == required_weight_keys


def test_fitness_weights_rejects_undocumented_keys(tmp_path) -> None:
    config_path = tmp_path / "fitness_weights.json"
    config_path.write_text(
        json.dumps(
            {
                "version": 1,
                "weights": {
                    "correctness_score": 0.3,
                    "efficiency_score": 0.2,
                    "policy_compliance_score": 0.2,
                    "goal_alignment_score": 0.15,
                    "simulated_market_score": 0.15,
                    "undocumented": 0.01,
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unexpected_weight_keys"):
        EconomicFitnessEvaluator(config_path=config_path)


def test_fitness_explainability_contains_threshold_and_hash() -> None:
    evaluator = EconomicFitnessEvaluator()
    result = evaluator.evaluate({"tests_ok": True, "sandbox_ok": True, "constitution_ok": True, "policy_valid": True})
    as_dict = result.to_dict()

    assert as_dict["fitness_threshold"] > 0
    assert as_dict["config_version"] >= 1
    assert as_dict["config_hash"].startswith("sha256:")
    assert set(as_dict["weighted_contributions"].keys()) == set(as_dict["weights"].keys())
