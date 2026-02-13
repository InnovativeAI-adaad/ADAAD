# SPDX-License-Identifier: Apache-2.0

from app.agents.mutation_request import MutationRequest, MutationTarget
from runtime.analysis.impact_predictor import ImpactPredictor


def test_impact_predictor_scores_targeted_mutation(tmp_path) -> None:
    predictor = ImpactPredictor(tmp_path)
    req = MutationRequest(
        agent_id="alpha",
        generation_ts="2026-01-01T00:00:00Z",
        intent="refactor",
        ops=[],
        signature="sig",
        nonce="n1",
        targets=[MutationTarget(agent_id="alpha", path="x.py", target_type="code", ops=[{"op": "replace"}])],
    )
    prediction = predictor.predict(req)
    assert "alpha/x.py" in prediction.affected_files
    assert prediction.risk_score >= 0.0


def test_impact_predictor_defaults_to_dna_path(tmp_path) -> None:
    predictor = ImpactPredictor(tmp_path)
    req = MutationRequest(
        agent_id="beta",
        generation_ts="2026-01-01T00:00:00Z",
        intent="mutate",
        ops=[{"op": "set"}],
        signature="sig",
        nonce="n1",
    )
    prediction = predictor.predict(req)
    assert "beta/dna.json" in prediction.affected_files
