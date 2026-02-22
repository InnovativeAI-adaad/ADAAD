# SPDX-License-Identifier: Apache-2.0

from runtime.sandbox.evidence import SandboxEvidenceLedger, build_sandbox_evidence


def test_sandbox_evidence_ledger_hash_chain(tmp_path):
    ledger = SandboxEvidenceLedger(tmp_path / "sandbox_evidence.jsonl")
    payload = build_sandbox_evidence(
        manifest={"mutation_id": "m1", "epoch_id": "e1", "replay_seed": "0000000000000001"},
        result={"stdout": "ok", "stderr": "", "duration_s": 0.1, "memory_mb": 10, "disk_mb": 0, "returncode": 0},
        policy_hash="sha256:" + ("1" * 64),
        syscall_trace=("open", "read"),
        provider_ts="2026-02-14T00:00:00Z",
    )
    first = ledger.append(payload)
    second = ledger.append(payload)
    assert first["prev_hash"].startswith("sha256:")
    assert second["prev_hash"] == first["hash"]
    assert payload["evidence_hash"].startswith("sha256:")
    assert payload["resource_usage_hash"].startswith("sha256:")
    assert payload["sandbox_policy_hash"] == payload["policy_hash"]
    assert payload["syscall_fingerprint"].startswith("sha256:")
    assert payload["events"] == []

    assert payload["isolation_mode"] == "process"
    assert payload["preflight"]["ok"] is True



def test_sandbox_evidence_resource_accounting_is_deterministic():
    manifest = {"mutation_id": "m1", "epoch_id": "e1", "replay_seed": "0000000000000001"}
    result = {"stdout": "ok", "stderr": "", "duration_s": 0.1, "memory_mb": 10, "disk_mb": 0, "returncode": 0}
    first = build_sandbox_evidence(
        manifest=manifest,
        result=result,
        policy_hash="sha256:" + ("1" * 64),
        syscall_trace=("open", "read"),
        provider_ts="2026-02-14T00:00:00Z",
    )
    second = build_sandbox_evidence(
        manifest=manifest,
        result=result,
        policy_hash="sha256:" + ("1" * 64),
        syscall_trace=("open", "read"),
        provider_ts="2026-02-14T00:00:00Z",
    )

    assert first["resource_usage"] == second["resource_usage"]
    assert first["resource_usage"]["duration_s"] == 0.1
    assert first["resource_usage_hash"] == second["resource_usage_hash"]
