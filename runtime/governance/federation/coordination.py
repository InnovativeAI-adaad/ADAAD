# SPDX-License-Identifier: Apache-2.0
"""Deterministic federation coordination and conflict-resolution helpers.

Mutation rationale:
- Federation negotiation and reconciliation outcomes are modeled as immutable,
  canonicalized payloads so that event digests and replay outcomes stay deterministic.

Expected invariants:
- Peer ordering and vote tallying are stable for identical inputs.
- Governance precedence is explicit and fail-closed when local governance diverges.
- Federation decisions persisted to the lineage ledger are append-only and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Dict, Iterable, List, Literal

from runtime.evolution.lineage_v2 import LineageLedgerV2

DECISION_CLASS_CONSENSUS = "consensus"
DECISION_CLASS_QUORUM = "quorum"
DECISION_CLASS_CONFLICT = "conflict"
DECISION_CLASS_REJECTED = "rejected"
DECISION_CLASS_LOCAL_OVERRIDE = "local_override"

POLICY_PRECEDENCE_LOCAL = "local"
POLICY_PRECEDENCE_FEDERATED = "federated"
POLICY_PRECEDENCE_BOTH = "both"


@dataclass(frozen=True)
class FederationVote:
    peer_id: str
    policy_version: str
    manifest_digest: str
    decision: Literal["accept", "reject"] = "accept"


@dataclass(frozen=True)
class FederationPolicyExchange:
    local_peer_id: str
    local_policy_version: str
    local_manifest_digest: str
    peer_versions: Dict[str, str] = field(default_factory=dict)
    local_certificate: Dict[str, str] = field(default_factory=dict)
    peer_certificates: Dict[str, Dict[str, str]] = field(default_factory=dict)

    def canonical_payload(self) -> Dict[str, object]:
        return {
            "local_peer_id": self.local_peer_id,
            "local_policy_version": self.local_policy_version,
            "local_manifest_digest": self.local_manifest_digest,
            "local_certificate": {key: self.local_certificate[key] for key in sorted(self.local_certificate)},
            "peer_versions": {key: self.peer_versions[key] for key in sorted(self.peer_versions)},
            "peer_certificates": {
                peer_id: {
                    cert_key: self.peer_certificates[peer_id][cert_key]
                    for cert_key in sorted(self.peer_certificates[peer_id])
                }
                for peer_id in sorted(self.peer_certificates)
            },
        }

    def exchange_digest(self) -> str:
        encoded = json.dumps(self.canonical_payload(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + sha256(encoded).hexdigest()


def _vote_payload(votes: Iterable[FederationVote]) -> List[Dict[str, str]]:
    rows = [
        {
            "peer_id": vote.peer_id,
            "policy_version": vote.policy_version,
            "manifest_digest": vote.manifest_digest,
            "decision": vote.decision,
        }
        for vote in votes
    ]
    return sorted(rows, key=lambda item: (item["peer_id"], item["policy_version"], item["manifest_digest"], item["decision"]))


def _vote_digest(votes: Iterable[FederationVote]) -> str:
    encoded = json.dumps(_vote_payload(votes), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def evaluate_federation_decision(
    exchange: FederationPolicyExchange,
    votes: List[FederationVote],
    *,
    quorum_size: int,
) -> FederationDecision:
    """Evaluate deterministic quorum/consensus decision from local + peer votes."""
    tallies: Dict[str, int] = {exchange.local_policy_version: 1}
    manifest_digests: Dict[str, str] = {exchange.local_peer_id: exchange.local_manifest_digest}

    for vote in sorted(votes, key=lambda item: item.peer_id):
        manifest_digests[vote.peer_id] = vote.manifest_digest
        if vote.decision != "accept":
            continue
        tallies[vote.policy_version] = tallies.get(vote.policy_version, 0) + 1

    sorted_versions = sorted(tallies.items(), key=lambda item: (-item[1], item[0]))
    selected_policy_version, selected_count = sorted_versions[0]
    consensus = len(sorted_versions) == 1
    has_quorum = selected_count >= quorum_size

    if consensus and has_quorum:
        decision_class = DECISION_CLASS_CONSENSUS
        reconciliation_actions = ["bind_policy_version"]
    elif has_quorum:
        decision_class = DECISION_CLASS_QUORUM
        reconciliation_actions = ["stage_majority_policy", "request_minor_peer_reconciliation"]
    elif len(sorted_versions) > 1:
        decision_class = DECISION_CLASS_CONFLICT
        selected_policy_version = exchange.local_policy_version
        reconciliation_actions = ["freeze_federated_upgrade", "require_local_governance_review"]
    else:
        decision_class = DECISION_CLASS_REJECTED
        reconciliation_actions = ["reject_federated_policy_update"]

    return FederationDecision(
        decision_class=decision_class,
        selected_policy_version=selected_policy_version,
        peer_ids=sorted(manifest_digests),
        manifest_digests={peer_id: manifest_digests[peer_id] for peer_id in sorted(manifest_digests)},
        reconciliation_actions=reconciliation_actions,
        quorum_size=max(1, quorum_size),
        vote_digest=_vote_digest(votes),
    )


@dataclass(frozen=True)
class FederationDecision:
    decision_class: str
    selected_policy_version: str
    peer_ids: List[str]
    manifest_digests: Dict[str, str]
    reconciliation_actions: List[str]
    quorum_size: int
    vote_digest: str


def resolve_governance_precedence(
    *,
    local_passed: bool,
    federated_passed: bool,
    policy_precedence: str = POLICY_PRECEDENCE_BOTH,
) -> Dict[str, object]:
    """Resolve final replay/governance pass decision with explicit precedence rules."""
    if policy_precedence == POLICY_PRECEDENCE_LOCAL:
        final_passed = local_passed
        source = POLICY_PRECEDENCE_LOCAL
    elif policy_precedence == POLICY_PRECEDENCE_FEDERATED:
        final_passed = federated_passed
        source = POLICY_PRECEDENCE_FEDERATED
    else:
        final_passed = local_passed and federated_passed
        source = POLICY_PRECEDENCE_BOTH

    if not local_passed and federated_passed:
        decision_class = DECISION_CLASS_LOCAL_OVERRIDE
    elif local_passed and not federated_passed:
        decision_class = DECISION_CLASS_CONFLICT
    elif final_passed:
        decision_class = DECISION_CLASS_CONSENSUS
    else:
        decision_class = DECISION_CLASS_REJECTED

    return {
        "passed": final_passed,
        "decision_class": decision_class,
        "precedence_source": source,
        "local_passed": local_passed,
        "federated_passed": federated_passed,
    }


def persist_federation_decision(
    ledger: LineageLedgerV2,
    *,
    epoch_id: str,
    exchange: FederationPolicyExchange,
    decision: FederationDecision,
) -> Dict[str, object]:
    payload = {
        "epoch_id": epoch_id,
        "local_peer_id": exchange.local_peer_id,
        "exchange_digest": exchange.exchange_digest(),
        "peer_ids": decision.peer_ids,
        "manifest_digests": decision.manifest_digests,
        "decision_class": decision.decision_class,
        "selected_policy_version": decision.selected_policy_version,
        "quorum_size": decision.quorum_size,
        "vote_digest": decision.vote_digest,
        "reconciliation_actions": decision.reconciliation_actions,
    }
    return ledger.append_event("FederationDecisionEvent", payload)


__all__ = [
    "DECISION_CLASS_CONFLICT",
    "DECISION_CLASS_CONSENSUS",
    "DECISION_CLASS_LOCAL_OVERRIDE",
    "DECISION_CLASS_QUORUM",
    "DECISION_CLASS_REJECTED",
    "POLICY_PRECEDENCE_BOTH",
    "POLICY_PRECEDENCE_FEDERATED",
    "POLICY_PRECEDENCE_LOCAL",
    "FederationDecision",
    "FederationPolicyExchange",
    "FederationVote",
    "evaluate_federation_decision",
    "persist_federation_decision",
    "resolve_governance_precedence",
]
