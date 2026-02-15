# SPDX-License-Identifier: Apache-2.0
"""Runtime replay verification and divergence handling."""

from __future__ import annotations

from typing import Any, Dict, Iterable

from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.replay import ReplayEngine
from runtime.governance.federation import (
    POLICY_PRECEDENCE_BOTH,
    resolve_governance_precedence,
)


class ReplayVerifier:
    def __init__(self, ledger: LineageLedgerV2, replay_engine: ReplayEngine, *, verify_every_n_mutations: int = 3) -> None:
        self.ledger = ledger
        self.replay_engine = replay_engine
        self.verify_every_n_mutations = max(1, verify_every_n_mutations)

    def should_verify(self, mutation_count: int) -> bool:
        return mutation_count > 0 and mutation_count % self.verify_every_n_mutations == 0

    def _classify_federated_divergence(
        self,
        *,
        expected_digest: str,
        replay_digest: str,
        attestations: Iterable[Dict[str, str]] | None,
    ) -> Dict[str, Any]:
        ordered = sorted(
            list(attestations or []),
            key=lambda item: (
                str(item.get("peer_id") or ""),
                str(item.get("attested_digest") or ""),
                str(item.get("manifest_digest") or ""),
                str(item.get("policy_version") or ""),
            ),
        )
        mismatched_peers = [
            str(item.get("peer_id") or "")
            for item in ordered
            if str(item.get("attested_digest") or "") not in {expected_digest, replay_digest}
        ]
        unique_attestations = {str(item.get("attested_digest") or "") for item in ordered if item.get("attested_digest")}

        if replay_digest != expected_digest and not ordered:
            divergence_class = "local_digest_mismatch"
        elif len(unique_attestations) > 1:
            divergence_class = "federated_split_brain"
        elif mismatched_peers:
            divergence_class = "cross_node_attestation_mismatch"
        else:
            divergence_class = "none"

        federated_passed = divergence_class == "none"
        return {
            "divergence_class": divergence_class,
            "federated_passed": federated_passed,
            "attestation_count": len(ordered),
            "mismatched_peers": mismatched_peers,
        }

    def verify_epoch(
        self,
        epoch_id: str,
        expected_digest: str,
        *,
        attestations: Iterable[Dict[str, str]] | None = None,
        policy_precedence: str = POLICY_PRECEDENCE_BOTH,
    ) -> Dict[str, Any]:
        replay_digest = self.replay_engine.compute_incremental_digest(epoch_id)
        local_passed = replay_digest == expected_digest
        federated = self._classify_federated_divergence(
            expected_digest=expected_digest,
            replay_digest=replay_digest,
            attestations=attestations,
        )
        precedence = resolve_governance_precedence(
            local_passed=local_passed,
            federated_passed=bool(federated["federated_passed"]),
            policy_precedence=policy_precedence,
        )
        passed = bool(precedence["passed"])

        event = {
            "epoch_id": epoch_id,
            "epoch_digest": expected_digest,
            "checkpoint_digest": expected_digest,
            "replay_digest": replay_digest,
            "replay_passed": passed,
            "local_replay_passed": local_passed,
            "federated_replay_passed": federated["federated_passed"],
            "divergence_class": federated["divergence_class"],
            "mismatched_peers": federated["mismatched_peers"],
            "governance_precedence": precedence["precedence_source"],
            "decision_class": precedence["decision_class"],
        }
        self.ledger.append_event("ReplayVerificationEvent", event)
        return event


__all__ = ["ReplayVerifier"]
