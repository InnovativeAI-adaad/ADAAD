# SPDX-License-Identifier: Apache-2.0
"""Runtime replay verification and divergence handling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable

from runtime.evolution.lineage_v2 import LineageLedgerV2
from runtime.evolution.replay import ReplayEngine
from runtime.governance.federation.coordination import (
    POLICY_PRECEDENCE_BOTH,
    resolve_governance_precedence,
)


class ReplayVerifier:
    def __init__(
        self,
        ledger: LineageLedgerV2,
        replay_engine: ReplayEngine,
        *,
        verify_every_n_mutations: int = 3,
        federation_state_path: str | Path = "federation_state.json",
    ) -> None:
        self.ledger = ledger
        self.replay_engine = replay_engine
        self.verify_every_n_mutations = max(1, verify_every_n_mutations)
        self.federation_state_path = Path(federation_state_path)

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
            divergence_class = "drift_local_digest_mismatch"
        elif len(unique_attestations) > 1:
            divergence_class = "drift_federated_split_brain"
        elif mismatched_peers:
            divergence_class = "drift_cross_node_attestation_mismatch"
        else:
            divergence_class = "none"

        federated_passed = divergence_class == "none"
        return {
            "divergence_class": divergence_class,
            "federated_passed": federated_passed,
            "attestation_count": len(ordered),
            "mismatched_peers": mismatched_peers,
            "ordered_attestations": ordered,
        }

    @staticmethod
    def _epoch_fingerprint(epoch_id: str, expected_digest: str, replay_digest: str, divergence_class: str) -> str:
        canonical = json.dumps(
            {
                "epoch_id": epoch_id,
                "expected_digest": expected_digest,
                "replay_digest": replay_digest,
                "divergence_class": divergence_class,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        from hashlib import sha256

        return "sha256:" + sha256(canonical.encode("utf-8")).hexdigest()

    def _persist_federation_state(self, payload: Dict[str, Any]) -> None:
        records = list(payload.get("exchange_records") or [])
        snapshot = {
            "version": 1,
            "records": records,
        }
        try:
            self.federation_state_path.parent.mkdir(parents=True, exist_ok=True)
            encoded = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True)
            self.federation_state_path.write_text(encoded + "\n", encoding="utf-8")
        except OSError:
            # Fail-closed governance must not be downgraded by auxiliary snapshot persistence failures.
            return

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
        drift_detected = str(federated["divergence_class"]) != "none"
        epoch_fingerprint = self._epoch_fingerprint(epoch_id, expected_digest, replay_digest, str(federated["divergence_class"]))

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
            "federation_drift_detected": drift_detected,
            "epoch_fingerprint": epoch_fingerprint,
            "passed": passed,
        }
        self.ledger.append_event("ReplayVerificationEvent", event)

        federation_state = {
            "exchange_records": [
                {
                    "epoch_id": epoch_id,
                    "expected_digest": expected_digest,
                    "replay_digest": replay_digest,
                    "divergence_class": federated["divergence_class"],
                    "attestation_count": federated["attestation_count"],
                    "epoch_fingerprint": epoch_fingerprint,
                    "peer_records": federated["ordered_attestations"],
                }
            ]
        }
        self._persist_federation_state(federation_state)

        if drift_detected:
            self.ledger.append_event(
                "FederationDivergenceEvent",
                {
                    "epoch_id": epoch_id,
                    "drift_class": federated["divergence_class"],
                    "epoch_fingerprint": epoch_fingerprint,
                    "mismatched_peers": federated["mismatched_peers"],
                },
            )
        else:
            self.ledger.append_event(
                "FederationVerificationEvent",
                {
                    "epoch_id": epoch_id,
                    "event_type": "federation_verified",
                    "epoch_fingerprint": epoch_fingerprint,
                    "attestation_count": federated["attestation_count"],
                },
            )
        return event


__all__ = ["ReplayVerifier"]
