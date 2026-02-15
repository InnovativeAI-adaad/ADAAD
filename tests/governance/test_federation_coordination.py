# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.replay import ReplayEngine
from runtime.evolution.replay_verifier import ReplayVerifier
from runtime.governance.federation import (
    DECISION_CLASS_CONFLICT,
    DECISION_CLASS_QUORUM,
    POLICY_PRECEDENCE_BOTH,
    POLICY_PRECEDENCE_LOCAL,
    FederationPolicyExchange,
    FederationVote,
    evaluate_federation_decision,
    persist_federation_decision,
)
from runtime.governance.founders_law_v2 import (
    COMPAT_DOWNLEVEL,
    LawManifest,
    LawModule,
    LawRef,
    LawRuleV2,
    ManifestSignature,
    evaluate_compatibility,
)


def _module(module_id: str, version: str = "2.0.0", *, requires: list[LawRef] | None = None) -> LawModule:
    return LawModule(
        id=module_id,
        version=version,
        kind="core",
        scope="both",
        applies_to=["epoch", "mutation"],
        trust_modes=["prod"],
        lifecycle_states=["proposed", "certified"],
        requires=requires or [],
        conflicts=[],
        supersedes=[],
        rules=[
            LawRuleV2(
                rule_id=f"{module_id}-RULE",
                name="sample-rule",
                description="sample",
                severity="hard",
                applies_to=["epoch"],
            )
        ],
    )


def _manifest(modules: list[LawModule]) -> LawManifest:
    return LawManifest(
        schema_version="2.0.0",
        node_id="node-a",
        law_version="founders_law@v2",
        trust_mode="prod",
        epoch_id="epoch-fed",
        modules=modules,
        signature=ManifestSignature(algo="ed25519", key_id="signer", value="sig"),
    )


def _seed_epoch(ledger: LineageLedgerV2, epoch_id: str) -> str:
    ledger.append_event("EpochStartEvent", {"epoch_id": epoch_id})
    payload = {
        "epoch_id": epoch_id,
        "bundle_id": "b1",
        "impact": 0.1,
        "strategy_set": ["s1"],
        "certificate": {
            "bundle_id": "b1",
            "strategy_set": ["s1"],
            "strategy_snapshot_hash": "h1",
            "strategy_version_set": ["v1"],
        },
    }
    return ledger.append_bundle_with_digest(epoch_id, payload)


def test_federation_split_brain_classifies_deterministically(tmp_path: Path) -> None:
    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    expected = _seed_epoch(ledger, "epoch-1")
    verifier = ReplayVerifier(ledger, ReplayEngine(ledger), verify_every_n_mutations=1)

    result = verifier.verify_epoch(
        "epoch-1",
        expected,
        attestations=[
            {"peer_id": "peer-b", "attested_digest": "sha256:peer-b", "manifest_digest": "m2", "policy_version": "2.1.0"},
            {"peer_id": "peer-a", "attested_digest": "sha256:peer-a", "manifest_digest": "m1", "policy_version": "2.1.0"},
        ],
        policy_precedence=POLICY_PRECEDENCE_BOTH,
    )

    assert result["divergence_class"] == "federated_split_brain"
    assert result["replay_passed"] is False


def test_downlevel_compatibility_supported_for_federated_policy_exchange() -> None:
    local = _manifest([_module("FL-Core"), _module("FL-Safety")])
    peer = _manifest([_module("FL-Core"), _module("FL-Safety"), _module("FL-Federation")])

    compat = evaluate_compatibility(local, peer)

    assert compat.compat_class == COMPAT_DOWNLEVEL


def test_conflicting_policy_versions_record_conflict_and_ledger_payload(tmp_path: Path) -> None:
    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    exchange = FederationPolicyExchange(
        local_peer_id="node-a",
        local_policy_version="2.0.0",
        local_manifest_digest="sha256:m-local",
        peer_versions={"node-b": "2.1.0", "node-c": "2.0.0"},
    )
    decision = evaluate_federation_decision(
        exchange,
        votes=[
            FederationVote(peer_id="node-b", policy_version="2.1.0", manifest_digest="sha256:m-b"),
            FederationVote(peer_id="node-c", policy_version="2.1.0", manifest_digest="sha256:m-c"),
        ],
        quorum_size=3,
    )
    persist_federation_decision(ledger, epoch_id="epoch-2", exchange=exchange, decision=decision)

    events = [entry for entry in ledger.read_all() if entry.get("type") == "FederationDecisionEvent"]

    assert decision.decision_class == DECISION_CLASS_CONFLICT
    assert events[-1]["payload"]["peer_ids"] == ["node-a", "node-b", "node-c"]
    assert events[-1]["payload"]["decision_class"] == DECISION_CLASS_CONFLICT
    assert events[-1]["payload"]["reconciliation_actions"]


def test_deterministic_convergence_stable_for_vote_ordering(tmp_path: Path) -> None:
    exchange = FederationPolicyExchange(
        local_peer_id="node-a",
        local_policy_version="2.0.0",
        local_manifest_digest="sha256:m-local",
        peer_versions={"node-b": "2.1.0", "node-c": "2.1.0"},
    )
    votes_a = [
        FederationVote(peer_id="node-c", policy_version="2.1.0", manifest_digest="sha256:m-c"),
        FederationVote(peer_id="node-b", policy_version="2.1.0", manifest_digest="sha256:m-b"),
    ]
    votes_b = list(reversed(votes_a))

    decision_a = evaluate_federation_decision(exchange, votes_a, quorum_size=2)
    decision_b = evaluate_federation_decision(exchange, votes_b, quorum_size=2)

    assert decision_a.decision_class == DECISION_CLASS_QUORUM
    assert decision_a.selected_policy_version == "2.1.0"
    assert decision_a.vote_digest == decision_b.vote_digest

    ledger = LineageLedgerV2(tmp_path / "lineage_v2.jsonl")
    epoch_digest = _seed_epoch(ledger, "epoch-3")
    verifier = ReplayVerifier(ledger, ReplayEngine(ledger), verify_every_n_mutations=1)
    replay = verifier.verify_epoch("epoch-3", epoch_digest, policy_precedence=POLICY_PRECEDENCE_LOCAL)
    assert replay["replay_passed"] is True
