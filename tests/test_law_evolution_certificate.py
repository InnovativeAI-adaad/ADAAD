from __future__ import annotations

from runtime.governance.founders_law_v2 import LawManifest, LawModule, LawRef, LawRuleV2, ManifestSignature
from runtime.governance.law_evolution_certificate import issue_certificate, validate_certificate


def _module(module_id: str, version: str = "2.0.0") -> LawModule:
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


def _manifest(epoch_id: str, modules: list[LawModule]) -> LawManifest:
    return LawManifest(
        schema_version="2.0.0",
        node_id="adaad-node-ponca-01",
        law_version="founders_law@v2",
        trust_mode="prod",
        epoch_id=epoch_id,
        modules=modules,
        signature=ManifestSignature(algo="ed25519", key_id="law-signer-prod-01", value="sig"),
    )


def test_issue_and_validate_certificate_success() -> None:
    old_manifest = _manifest("epoch-1", [_module("FL-Core-Invariants", "2.0.0")])
    new_manifest = _manifest("epoch-2", [_module("FL-Core-Invariants", "2.1.0")])

    cert = issue_certificate(
        old_manifest,
        new_manifest,
        reason="upgrade core invariants",
        signer_key_id="law-signer-prod-01",
        replay_safe=True,
        signature="base64sig",
    )

    errors = validate_certificate(cert, old_manifest=old_manifest, new_manifest=new_manifest, require_replay_safe=True)

    assert errors == []


def test_validate_certificate_rejects_unchanged_manifest() -> None:
    old_manifest = _manifest("epoch-1", [_module("FL-Core-Invariants", "2.0.0")])
    new_manifest = _manifest("epoch-2", [_module("FL-Core-Invariants", "2.0.0")])

    cert = issue_certificate(
        old_manifest,
        new_manifest,
        reason="no-op",
        signer_key_id="law-signer-prod-01",
        replay_safe=False,
        signature="base64sig",
    )

    errors = validate_certificate(cert, old_manifest=old_manifest, new_manifest=new_manifest)

    assert "certificate must reference a manifest change" in errors


def test_validate_certificate_requires_signature() -> None:
    old_manifest = _manifest("epoch-1", [_module("FL-Core-Invariants", "2.0.0")])
    new_manifest = _manifest("epoch-2", [_module("FL-Core-Invariants", "2.1.0")])

    cert = issue_certificate(
        old_manifest,
        new_manifest,
        reason="upgrade",
        signer_key_id="law-signer-prod-01",
        replay_safe=True,
        signature="",
    )

    errors = validate_certificate(cert, old_manifest=old_manifest, new_manifest=new_manifest)

    assert "missing certificate signature" in errors
