# SPDX-License-Identifier: Apache-2.0

from app.agents.mutation_request import MutationRequest
from runtime.evolution.entropy_detector import detect_entropy_metadata
from runtime.evolution.entropy_policy import EntropyPolicy, enforce_entropy_policy


def test_entropy_detection_and_policy_passes():
    request = MutationRequest(
        agent_id="a",
        generation_ts="now",
        intent="x",
        ops=[{"op": "set", "path": "/x", "value": 1}],
        signature="s",
        nonce="n",
    )
    metadata = detect_entropy_metadata(request, mutation_id="m", epoch_id="e")
    policy = EntropyPolicy("p1", per_mutation_ceiling_bits=64, per_epoch_ceiling_bits=1024)
    verdict = enforce_entropy_policy(policy=policy, mutation_bits=metadata.estimated_bits, epoch_bits=metadata.estimated_bits)
    assert verdict["passed"]
    assert verdict["policy_hash"].startswith("sha256:")
