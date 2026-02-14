# SPDX-License-Identifier: Apache-2.0

from runtime.sandbox.evidence import build_sandbox_evidence
from runtime.sandbox.replay import replay_sandbox_execution


def _build_valid_replay_inputs():
    manifest = {"mutation_id": "m1", "epoch_id": "e1", "replay_seed": "0000000000000001"}
    evidence = build_sandbox_evidence(
        manifest=manifest,
        result={"stdout": "hello", "stderr": "", "duration_s": 0.1, "memory_mb": 10, "disk_mb": 0, "returncode": 0},
        policy_hash="sha256:" + ("1" * 64),
        syscall_trace=("open", "read"),
        provider_ts="2026-02-14T00:00:00Z",
    )
    return manifest, evidence


def test_replay_sandbox_execution_passes_for_valid_evidence():
    manifest, evidence = _build_valid_replay_inputs()
    replay = replay_sandbox_execution(manifest, evidence)
    assert replay["passed"] is True


def test_replay_sandbox_execution_detects_tampered_manifest():
    manifest, evidence = _build_valid_replay_inputs()
    tampered_manifest = dict(manifest)
    tampered_manifest["mutation_id"] = "tampered"
    replay = replay_sandbox_execution(tampered_manifest, evidence)
    assert replay["passed"] is False
    assert replay["checks"]["manifest_hash"] is False


def test_replay_sandbox_execution_detects_tampered_stdout():
    manifest, evidence = _build_valid_replay_inputs()
    tampered_evidence = dict(evidence)
    tampered_evidence["stdout"] = "tampered"
    replay = replay_sandbox_execution(manifest, tampered_evidence)
    assert replay["passed"] is False
    assert replay["checks"]["stdout_hash"] is False


def test_replay_sandbox_execution_detects_tampered_stderr():
    manifest, evidence = _build_valid_replay_inputs()
    tampered_evidence = dict(evidence)
    tampered_evidence["stderr"] = "tampered"
    replay = replay_sandbox_execution(manifest, tampered_evidence)
    assert replay["passed"] is False
    assert replay["checks"]["stderr_hash"] is False


def test_replay_sandbox_execution_detects_tampered_syscall_trace():
    manifest, evidence = _build_valid_replay_inputs()
    tampered_evidence = dict(evidence)
    tampered_evidence["syscall_trace"] = ["open", "execve"]
    replay = replay_sandbox_execution(manifest, tampered_evidence)
    assert replay["passed"] is False
    assert replay["checks"]["syscall_trace_hash"] is False


def test_replay_sandbox_execution_detects_tampered_resource_usage():
    manifest, evidence = _build_valid_replay_inputs()
    tampered_evidence = dict(evidence)
    tampered_evidence["resource_usage"] = {"duration_s": 0.1, "memory_mb": 999.0, "disk_mb": 0.0}
    replay = replay_sandbox_execution(manifest, tampered_evidence)
    assert replay["passed"] is False
    assert replay["checks"]["resource_usage_hash"] is False
