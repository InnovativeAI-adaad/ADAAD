from __future__ import annotations

from pathlib import Path

import pytest

from runtime.evolution.epoch import EpochManager
from runtime.governance.founders_law_v2 import LawManifest, LawModule, LawRef, LawRuleV2, ManifestSignature
from runtime.governance.foundation import SeededDeterminismProvider
from runtime.governance.law_evolution_certificate import issue_certificate, law_surface_digest


class _Governor:
    def __init__(self) -> None:
        self.recovery_tier = type("Tier", (), {"value": "audit"})()

    def _epoch_started(self, _epoch_id: str) -> bool:
        return False

    def mark_epoch_start(self, _epoch_id: str, _metadata: dict) -> None:
        return None

    def mark_epoch_end(self, _epoch_id: str, _metadata: dict) -> None:
        return None


class _Ledger:
    def compute_cumulative_epoch_digest(self, _epoch_id: str) -> str:
        return "sha256:0"

    def append_event(self, _event: str, _payload: dict) -> None:
        return None


def _module(module_id: str, version: str) -> LawModule:
    return LawModule(
        id=module_id,
        version=version,
        kind="core",
        scope="both",
        applies_to=["epoch", "mutation"],
        trust_modes=["prod"],
        lifecycle_states=["proposed", "certified", "executing", "completed"],
        requires=[],
        conflicts=[],
        supersedes=[LawRef(id=module_id, version_range="<2.0.0")],
        rules=[
            LawRuleV2(
                rule_id=f"{module_id}-RULE",
                name="rule",
                description="desc",
                severity="hard",
                applies_to=["epoch"],
            )
        ],
    )


def _manifest(epoch_id: str, version: str) -> LawManifest:
    return LawManifest(
        schema_version="2.0.0",
        node_id="adaad-node-01",
        law_version="founders_law@v2",
        trust_mode="prod",
        epoch_id=epoch_id,
        modules=[_module("FL-Core-Invariants", version)],
        signature=ManifestSignature(algo="ed25519", key_id="law-signer-prod-01", value="sig"),
    )


def test_rotate_epoch_requires_certificate_for_law_surface_change(tmp_path: Path) -> None:
    manager = EpochManager(_Governor(), _Ledger(), state_path=tmp_path / "current_epoch.json", provider=SeededDeterminismProvider(seed="epoch-law-test"))
    manager.load_or_create()

    old_manifest = _manifest("epoch-old", "2.0.0")
    new_manifest = _manifest("epoch-new", "2.1.0")

    with pytest.raises(ValueError, match="law transition requires a law evolution certificate"):
        manager.rotate_epoch(
            "law_upgrade",
            old_law_manifest=old_manifest,
            new_law_manifest=new_manifest,
        )


def test_rotate_epoch_embeds_law_metadata_with_valid_certificate(tmp_path: Path) -> None:
    manager = EpochManager(_Governor(), _Ledger(), state_path=tmp_path / "current_epoch.json", provider=SeededDeterminismProvider(seed="epoch-law-test"))
    manager.load_or_create()

    old_manifest = _manifest("epoch-old", "2.0.0")
    new_manifest = _manifest("epoch-new", "2.1.0")
    cert = issue_certificate(
        old_manifest,
        new_manifest,
        reason="upgrade",
        signer_key_id="law-signer-prod-01",
        replay_safe=True,
        signature="base64sig",
    )

    state = manager.rotate_epoch(
        "law_upgrade",
        old_law_manifest=old_manifest,
        new_law_manifest=new_manifest,
        law_certificate=cert,
        require_replay_safe_law_cert=True,
    )

    assert state.metadata["law_surface_digest"] == law_surface_digest(new_manifest)
    assert state.metadata["law_evolution_certificate_id"] == cert.certificate_id
    assert state.metadata["law_trust_mode"] == "prod"
