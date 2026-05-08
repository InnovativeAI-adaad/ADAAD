# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.orchestration.adaad_trigger import (
    AdaadTriggerOrchestrator,
    GitMutationAdapter,
    LedgerSchemaError,
    VirtualLedgerWriter,
    parse_trigger,
)

pytestmark = pytest.mark.regression_standard


class RecordingGitAdapter:
    def __init__(self) -> None:
        self.operations: list[str] = []

    def stage(self, *, simulation: bool) -> dict[str, object]:
        self.operations.append("stage")
        return {"status": "executed", "simulation": simulation, "operation": "git_add"}

    def merge(self, *, simulation: bool) -> dict[str, object]:
        self.operations.append("merge")
        return {"status": "executed", "simulation": simulation, "operation": "git_merge"}


class FailingAttestationLedger(VirtualLedgerWriter):
    def write_event(self, event):  # type: ignore[override]
        if event.get("event_type") == "merge_attestation.v1":
            raise RuntimeError("ledger_append_failed")
        return super().write_event(event)


@pytest.mark.parametrize(
    ("raw_command", "expected_action"),
    [
        ("ADAAD run", "run"),
        ("ADAAD status", "status"),
        ("ADAAD audit", "audit"),
        ("ADAAD retry", "retry"),
        ("ADAAD preflight", "preflight"),
        ("ADAAD verify", "verify"),
        ("ADAAD dry-run", "dry_run"),
        ("ADAAD simulate", "simulate"),
    ],
)
def test_parse_trigger_accepts_supported_actions(raw_command: str, expected_action: str) -> None:
    request = parse_trigger(raw_command)

    assert request.principal == "ADAAD"
    assert request.action == expected_action
    assert request.action in ALLOWED_ACTIONS
    assert request.simulation is (expected_action == "simulate")
    assert request.merge_authority is False


def test_parse_trigger_rejects_unknown_action() -> None:
    with pytest.raises(ValueError, match="unsupported_action"):
        parse_trigger("ADAAD unsupported-action")


def test_parse_trigger_defaults_to_run_when_action_is_omitted() -> None:
    request = parse_trigger("DEVADAAD")

    assert request.principal == "DEVADAAD"
    assert request.action == "run"
    assert request.simulation is False
    assert request.merge_authority is True


def test_run_status_payload_uses_canonical_action_name(tmp_path: Path) -> None:
    ledger = VirtualLedgerWriter()
    orchestrator = AdaadTriggerOrchestrator(
        repo_root=tmp_path,
        ledger_writer=ledger,
        git_mutation_adapter=RecordingGitAdapter(),
    )

    envelope = orchestrator.run("ADAAD dry-run", scenario="dependency_blocked")

    assert envelope["request"].action == "dry_run"
    assert envelope["ledger"]["event_type"] == "adaad_orchestration_attempt.v1"
    assert ledger.events[-1]["payload"]["action"] == "dry_run"


def test_virtual_ledger_writer_validates_required_schema_keys() -> None:
    ledger = VirtualLedgerWriter()

    with pytest.raises(LedgerSchemaError, match="ledger_schema_missing"):
        ledger.write_event({"event_type": "x"})


def test_simulation_mode_preserves_formatting_and_disables_mutations(tmp_path: Path) -> None:
    orchestrator = AdaadTriggerOrchestrator(repo_root=tmp_path)

    envelope = orchestrator.run("ADAAD simulate", scenario="dependency_blocked")

    assert envelope["simulation"] is True
    assert envelope["status"] == "blocked"
    assert envelope["decision"]["evaluated"] is True
    assert envelope["decision"]["allow_git_mutations"] is False
    assert envelope["decision"]["mutation_kind"] == "simulated"
    assert envelope["stage_result"] == {
        "status": "skipped",
        "reason": "blocked",
        "simulation": True,
        "operation": "git_add",
    }
    assert envelope["merge_result"] == {
        "status": "skipped",
        "reason": "blocked",
        "simulation": True,
        "operation": "git_merge",
    }
    assert "simulation=true" in envelope["output"]
    assert "Decision: deny" in envelope["output"]
    assert "Repository mutation: not_mutated" in envelope["output"]
    assert "tier_0:" in envelope["output"]


def test_non_simulation_mode_can_execute_stage_operation(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "demo.txt").write_text("data\n", encoding="utf-8")

    orchestrator = AdaadTriggerOrchestrator(repo_root=tmp_path)
    envelope = orchestrator.run("ADAAD", scenario="merge_ready")

    assert envelope["simulation"] is False
    assert envelope["decision"]["allow_git_mutations"] is True
    assert envelope["decision"]["mutated_repository_state"] is True
    assert envelope["stage_result"]["status"] == "executed"


def test_end_to_end_simulation_never_mutates_git_state(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=tmp_path, check=True)
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "seed.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=tmp_path, check=True, capture_output=True, text=True)

    pre_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()
    pre_status = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_path, check=True, capture_output=True, text=True).stdout

    script = Path(__file__).resolve().parents[1] / "scripts" / "run_adaad_trigger.py"
    subprocess.run(
        ["python", str(script), "ADAAD simulate", "--scenario", "tier1_failure"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    post_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()
    post_status = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_path, check=True, capture_output=True, text=True).stdout

    assert pre_head == post_head
    assert pre_status == post_status == ""


def test_run_blocks_git_mutations_for_tier1_failure(tmp_path: Path) -> None:
    git_adapter = RecordingGitAdapter()
    orchestrator = AdaadTriggerOrchestrator(repo_root=tmp_path, git_mutation_adapter=git_adapter)

    envelope = orchestrator.run("ADAAD", scenario="tier1_failure")

    assert envelope["status"] == "blocked"
    assert envelope["blocked_reason"] == "tier_1_failed"
    assert envelope["decision"]["all_required_gates_passed"] is False
    assert envelope["decision"]["allow_git_mutations"] is False
    assert envelope["decision"]["evaluated_gates"]["tier_1"]["passed"] is False
    assert envelope["stage_result"] == {
        "status": "skipped",
        "reason": "blocked",
        "simulation": False,
        "operation": "git_add",
    }
    assert envelope["merge_result"] == {
        "status": "skipped",
        "reason": "blocked",
        "simulation": False,
        "operation": "git_merge",
    }
    assert git_adapter.stage_calls == 0
    assert git_adapter.merge_calls == 0
    assert "Decision: deny" in envelope["output"]
    assert "Repository mutation: not_mutated" in envelope["output"]


def test_devadaad_merge_ready_requires_verified_sha_replay_context(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "demo.txt").write_text("data\n", encoding="utf-8")
    ledger = VirtualLedgerWriter()
    git_adapter = RecordingGitAdapter()
    orchestrator = AdaadTriggerOrchestrator(repo_root=tmp_path, ledger_writer=ledger, git_mutation_adapter=git_adapter)

    envelope = orchestrator.run("DEVADAAD simulate", scenario="merge_ready")

    assert envelope["status"] == "ready"
    assert envelope["decision"]["allow_git_mutations"] is True
    assert envelope["decision"]["mutated_repository_state"] is True
    assert envelope["replay_gate_pass"] is True
    assert envelope["replay_verification"]["verified_sha"] == "c" * 40
    assert envelope["merge_attestation"]["event"]["event_type"] == "merge_attestation.v1"
    assert envelope["merge_attestation"]["event"]["payload"]["pr_id"] == "PR-PHASE65-01"
    assert ledger.events[-1]["event_type"] == "merge_attestation.v1"
    assert git_adapter.operations == ["stage", "merge"]
    assert "replay_verified_sha_context: PASS" in envelope["output"]
    assert "merge_attestation: PASS" in envelope["output"]

def test_devadaad_executes_real_merge_pinned_to_verified_sha(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=tmp_path, check=True)
    (tmp_path / "demo.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "demo.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "demo.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "feature"], cwd=tmp_path, check=True, capture_output=True, text=True)
    verified_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "checkout", "main"], cwd=tmp_path, check=True, capture_output=True, text=True)

    orchestrator = AdaadTriggerOrchestrator(repo_root=tmp_path)
    envelope = orchestrator.run(
        "DEVADAAD",
        scenario="merge_ready",
        replay_verification={
            "manifest_path": "security/replay_manifests/verified-sha.replay_manifest.v1.json",
            "bundle_digest": "sha256:" + ("d" * 64),
            "verification_result": "pass",
            "verified_sha": verified_sha,
            "merge_target_sha": verified_sha,
            "schema_valid": True,
            "signature_valid": True,
            "divergence": False,
        },
    )

    merge_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    merge_parents = subprocess.run(
        ["git", "show", "--format=%P", "--no-patch", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip().split()

    assert envelope["status"] == "merged"
    assert envelope["merge_result"]["status"] == "executed"
    assert envelope["verified_sha"] == verified_sha
    assert envelope["merge_target_sha"] == verified_sha
    assert envelope["merge_result"]["verified_sha"] == verified_sha
    assert envelope["merge_result"]["merge_target_sha"] == verified_sha
    assert envelope["merge_result"]["merge_commit_sha"] == merge_head
    assert verified_sha in merge_parents
    assert "merge_commit_sha:" in envelope["output"]


def test_devadaad_blocks_when_merge_sha_verification_is_missing(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "demo.txt").write_text("data\n", encoding="utf-8")
    orchestrator = AdaadTriggerOrchestrator(repo_root=tmp_path)

    envelope = orchestrator.run("DEVADAAD", scenario="merge_verification_missing")

    assert envelope["status"] == "blocked"
    assert envelope["replay_gate_pass"] is False
    assert envelope["blocked_reason"] == "missing_merge_sha_verification"
    assert envelope["merge_result"]["status"] == "blocked"
    assert envelope["merge_result"]["reason"] == "missing_merge_sha_verification"
    assert "merge_target_matches_verified_sha: FAIL" in envelope["output"]


def test_run_blocks_git_mutations_for_replay_divergence(tmp_path: Path) -> None:
    git_adapter = RecordingGitAdapter()
    orchestrator = AdaadTriggerOrchestrator(repo_root=tmp_path, git_mutation_adapter=git_adapter)

    envelope = orchestrator.run("DEVADAAD", scenario="replay_diverged")

    assert envelope["status"] == "blocked"
    assert envelope["replay_gate_pass"] is False
    assert envelope["blocked_reason"] == "replay_divergence_detected"
    assert envelope["decision"]["all_required_gates_passed"] is False
    assert envelope["decision"]["allow_git_mutations"] is False
    assert envelope["decision"]["evaluated_gates"]["tier_m"]["passed"] is False
    assert envelope["stage_result"] == {
        "status": "skipped",
        "reason": "blocked",
        "simulation": False,
        "operation": "git_add",
    }
    assert envelope["merge_result"] == {
        "status": "skipped",
        "reason": "blocked",
        "simulation": False,
        "operation": "git_merge",
    }
    assert git_adapter.stage_calls == 0
    assert git_adapter.merge_calls == 0
    assert "replay_verified_sha_context: FAIL" in envelope["output"]


def test_devadaad_merge_is_blocked_when_attestation_write_fails(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "demo.txt").write_text("data\n", encoding="utf-8")
    git_adapter = RecordingGitAdapter()
    orchestrator = AdaadTriggerOrchestrator(
        repo_root=tmp_path,
        ledger_writer=FailingAttestationLedger(),
        git_mutation_adapter=git_adapter,
    )

    envelope = orchestrator.run("DEVADAAD", scenario="merge_ready")

    assert envelope["status"] == "blocked"
    assert envelope["blocked_reason"] == "attestation_write_failed"
    assert envelope["merge_attestation"] is None
    assert envelope["merge_result"]["status"] == "blocked"
    assert git_adapter.operations == ["stage"]
    assert "merge_attestation: FAIL" in envelope["output"]


def test_git_mutation_adapter_maps_stage_timeout_with_stream_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = GitMutationAdapter(repo_root=tmp_path)

    def _timeout(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(
            cmd=["git", "add", "-A"],
            timeout=2,
            output="staged-output",
            stderr="staged-error",
        )

    monkeypatch.setattr(subprocess, "run", _timeout)

    with pytest.raises(RuntimeError, match="git_command_timeout:git_add") as excinfo:
        adapter.stage(simulation=False)

    assert "stdout=staged-output" in str(excinfo.value)
    assert "stderr=staged-error" in str(excinfo.value)


def test_merge_timeout_blocks_status_and_prevents_success_reporting(tmp_path: Path) -> None:
    class TimeoutOnMergeAdapter:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def stage(self, *, simulation: bool) -> dict[str, object]:
            self.calls.append("stage")
            return {"status": "executed", "simulation": simulation, "operation": "git_add"}

        def merge(self, *, simulation: bool, verified_sha: str, merge_target_sha: str) -> dict[str, object]:
            self.calls.append("merge")
            raise RuntimeError("git_command_timeout:git_merge:stderr=merge stalled")

    git_adapter = TimeoutOnMergeAdapter()
    orchestrator = AdaadTriggerOrchestrator(repo_root=tmp_path, git_mutation_adapter=git_adapter)

    envelope = orchestrator.run(
        "DEVADAAD",
        scenario="merge_ready",
        replay_verification={
            "manifest_path": "security/replay_manifests/verified-sha.replay_manifest.v1.json",
            "bundle_digest": "sha256:" + ("d" * 64),
            "verification_result": "pass",
            "verified_sha": "c" * 40,
            "merge_target_sha": "c" * 40,
            "schema_valid": True,
            "signature_valid": True,
            "divergence": False,
        },
    )

    assert envelope["status"] == "blocked"
    assert envelope["blocked_reason"].startswith("git_command_timeout:git_merge")
    assert envelope["merge_result"]["status"] == "blocked"
    assert envelope["stage_result"]["status"] == "blocked"
    assert git_adapter.calls == ["stage", "merge"]


def test_stage_timeout_blocks_before_merge_and_reports_blocked_state(tmp_path: Path) -> None:
    class TimeoutOnStageAdapter:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def stage(self, *, simulation: bool) -> dict[str, object]:
            self.calls.append("stage")
            raise RuntimeError("git_command_timeout:git_add:stderr=stage stalled")

        def merge(self, *, simulation: bool, verified_sha: str, merge_target_sha: str) -> dict[str, object]:
            self.calls.append("merge")
            return {"status": "executed", "simulation": simulation, "operation": "git_merge"}

    git_adapter = TimeoutOnStageAdapter()
    orchestrator = AdaadTriggerOrchestrator(repo_root=tmp_path, git_mutation_adapter=git_adapter)

    envelope = orchestrator.run(
        "DEVADAAD",
        scenario="merge_ready",
        replay_verification={
            "manifest_path": "security/replay_manifests/verified-sha.replay_manifest.v1.json",
            "bundle_digest": "sha256:" + ("d" * 64),
            "verification_result": "pass",
            "verified_sha": "c" * 40,
            "merge_target_sha": "c" * 40,
            "schema_valid": True,
            "signature_valid": True,
            "divergence": False,
        },
    )

    assert envelope["status"] == "blocked"
    assert envelope["blocked_reason"].startswith("git_command_timeout:git_add")
    assert envelope["stage_result"]["status"] == "blocked"
    assert envelope["merge_result"]["status"] == "skipped"
    assert git_adapter.calls == ["stage"]
