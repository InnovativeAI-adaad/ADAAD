from __future__ import annotations

from runtime.governance.founders_law_v2 import (
    COMPAT_DOWNLEVEL,
    COMPAT_FULL,
    COMPAT_INCOMPATIBLE,
    LawManifest,
    LawModule,
    LawRef,
    LawRuleV2,
    ManifestSignature,
    evaluate_compatibility,
    negotiate_manifests,
    semver_satisfies,
    validate_manifest,
)


def _module(module_id: str, version: str = "2.0.0", *, requires: list[LawRef] | None = None) -> LawModule:
    return LawModule(
        id=module_id,
        version=version,
        kind="core",
        scope="both",
        applies_to=["epoch", "mutation", "lifecycle"],
        trust_modes=["dev", "prod"],
        lifecycle_states=["proposed", "staged", "certified", "executing", "completed", "pruned"],
        requires=requires or [],
        conflicts=[],
        supersedes=[LawRef(id=module_id, version_range="<2.0.0")],
        rules=[
            LawRuleV2(
                rule_id=f"{module_id}-RULE",
                name="sample-rule",
                description="sample",
                severity="hard",
                applies_to=["epoch", "mutation"],
            )
        ],
    )


def _manifest(modules: list[LawModule], *, law_version: str = "founders_law@v2", trust_mode: str = "prod") -> LawManifest:
    return LawManifest(
        schema_version="2.0.0",
        node_id="adaad-node-01",
        law_version=law_version,
        trust_mode=trust_mode,
        epoch_id="epoch-abc",
        modules=modules,
        signature=ManifestSignature(algo="ed25519", key_id="law-signer-prod-01", value="sig"),
    )


def test_semver_satisfies_supports_comma_ranges() -> None:
    assert semver_satisfies("2.1.0", ">=2.0.0,<3.0.0")
    assert not semver_satisfies("3.1.0", ">=2.0.0,<3.0.0")


def test_validate_manifest_catches_missing_dependency() -> None:
    manifest = _manifest([
        _module("FL-Core-Invariants"),
        _module("FL-Mutation-Lifecycle", requires=[LawRef(id="FL-Security-Chain", version_range=">=2.0.0")]),
    ])

    errors = validate_manifest(manifest)

    assert any("requires missing dependency" in item for item in errors)


def test_evaluate_compatibility_full_when_shared_surface_valid() -> None:
    local = _manifest([_module("FL-Core-Invariants"), _module("FL-Mutation-Lifecycle")])
    peer = _manifest([
        _module("FL-Core-Invariants", version="2.0.1"),
        _module("FL-Mutation-Lifecycle", version="2.0.1"),
    ])

    result = evaluate_compatibility(local, peer)

    assert result.compat_class == COMPAT_FULL
    assert len(result.compat_digest) == 64


def test_evaluate_compatibility_downlevel_when_new_side_adds_module() -> None:
    local = _manifest([_module("FL-Core-Invariants"), _module("FL-Mutation-Lifecycle")])
    peer = _manifest([
        _module("FL-Core-Invariants"),
        _module("FL-Mutation-Lifecycle"),
        _module("FL-Federation"),
    ])

    result = evaluate_compatibility(local, peer)

    assert result.compat_class == COMPAT_DOWNLEVEL


def test_evaluate_compatibility_incompatible_on_law_version_mismatch() -> None:
    local = _manifest([_module("FL-Core-Invariants")], law_version="founders_law@v2")
    peer = _manifest([_module("FL-Core-Invariants")], law_version="founders_law@v3")

    result = evaluate_compatibility(local, peer)

    assert result.compat_class == COMPAT_INCOMPATIBLE


def test_negotiate_manifests_requires_matching_class_and_digest() -> None:
    local = _manifest([_module("FL-Core-Invariants"), _module("FL-Mutation-Lifecycle")])
    peer = _manifest([_module("FL-Core-Invariants"), _module("FL-Mutation-Lifecycle")])

    local_eval = evaluate_compatibility(local, peer)
    peer_eval = evaluate_compatibility(peer, local)

    outcome = negotiate_manifests(local, peer, peer_result=peer_eval)

    assert local_eval.compat_class == COMPAT_FULL
    assert outcome.state == "BOUND"
    assert outcome.compat_digest == local_eval.compat_digest
