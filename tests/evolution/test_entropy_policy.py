# SPDX-License-Identifier: Apache-2.0

from app.agents.mutation_request import MutationRequest
from runtime.evolution.entropy_detector import detect_entropy_metadata, observed_entropy_from_telemetry
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


def test_entropy_policy_rejects_hidden_rng_and_time_drift():
    request = MutationRequest(
        agent_id="a",
        generation_ts="now",
        intent="x",
        ops=[{"op": "set", "path": "/x", "value": 1}],
        signature="s",
        nonce="n",
    )
    metadata = detect_entropy_metadata(request, mutation_id="m", epoch_id="e")
    observed_bits, observed_sources = observed_entropy_from_telemetry(
        {"unseeded_rng_calls": 4, "wall_clock_reads": 3, "external_io_attempts": 0}
    )
    policy = EntropyPolicy("p1", per_mutation_ceiling_bits=metadata.estimated_bits + 10, per_epoch_ceiling_bits=2048)
    verdict = enforce_entropy_policy(
        policy=policy,
        mutation_bits=metadata.estimated_bits + observed_bits,
        declared_bits=metadata.estimated_bits,
        observed_bits=observed_bits,
        epoch_bits=metadata.estimated_bits + observed_bits,
    )
    assert not verdict["passed"]
    assert "runtime_rng" in observed_sources
    assert "runtime_clock" in observed_sources


def test_entropy_policy_rejects_fragmented_bursts_over_epoch_ceiling():
    policy = EntropyPolicy("p2", per_mutation_ceiling_bits=64, per_epoch_ceiling_bits=24)
    cumulative = 0
    for _ in range(3):
        first = enforce_entropy_policy(policy=policy, mutation_bits=8, declared_bits=8, observed_bits=0, epoch_bits=cumulative + 8)
        assert first["passed"]
        cumulative += 8
    verdict = enforce_entropy_policy(policy=policy, mutation_bits=8, declared_bits=8, observed_bits=0, epoch_bits=cumulative + 8)
    assert not verdict["passed"]
    assert verdict["reason"] == "entropy_ceiling_exceeded"
