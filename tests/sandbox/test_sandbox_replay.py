# SPDX-License-Identifier: Apache-2.0

from runtime.sandbox.replay import replay_sandbox_execution


def test_replay_sandbox_execution_detects_manifest_mismatch():
    manifest = {"mutation_id": "m1", "epoch_id": "e1", "replay_seed": "0000000000000001"}
    evidence = {
        "manifest_hash": "sha256:" + ("0" * 64),
        "stdout_hash": "sha256:" + ("0" * 64),
        "result": {"stdout": "hello"},
    }
    replay = replay_sandbox_execution(manifest, evidence)
    assert replay["passed"] is False
    assert replay["expected_manifest_hash"].startswith("sha256:")
