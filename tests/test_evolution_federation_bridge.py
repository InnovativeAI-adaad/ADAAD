# SPDX-License-Identifier: Apache-2.0
"""Tests for EvolutionFederationBridge — Phase 5 lifecycle integration.

Coverage:
  - on_mutation_cycle_end: happy path, broker error resilience
  - on_inbound_evaluation: no proposals, accepted, quarantined, error resilience
  - on_epoch_rotation: registration, idempotent, conflict detection
  - Audit events emitted (ledger_append_event called correctly)
  - Audit failures never block bridge hooks
  - Accessors: pending_outbound_count, accepted_count, quarantined_count
  - BridgeResult.to_dict() completeness
"""

from __future__ import annotations

import pytest
pytestmark = pytest.mark.regression_standard
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, call

from runtime.governance.federation.evolution_federation_bridge import (
    EvolutionFederationBridge,
    BridgeResult,
    _ZERO_HASH,
)
from runtime.governance.federation.federated_evidence_matrix import (
    EpochAlreadyRegisteredSameDigest,
    LocalEpochDigestConflictError,
)


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------
def _make_proposal(proposal_id: str = "prop-001", source_repo: str = "repo-a",
                   source_epoch_id: str = "epoch-1") -> MagicMock:
    p = MagicMock()
    p.proposal_id = proposal_id
    p.source_repo = source_repo
    p.source_epoch_id = source_epoch_id
    return p


def _make_accepted(proposal_id: str = "prop-001") -> MagicMock:
    acc = MagicMock()
    acc.proposal = _make_proposal(proposal_id=proposal_id)
    acc.acceptance_digest = "sha256:" + "a" * 64
    return acc


def _make_quarantined(proposal_id: str = "prop-001", reason: str = "gate_rejected") -> Dict:
    return {"proposal_id": proposal_id, "reason": reason}


def _make_broker(
    pending_outbound: Optional[List] = None,
    accepted: Optional[List] = None,
    quarantined: Optional[List] = None,
) -> MagicMock:
    broker = MagicMock()
    broker.pending_outbound.return_value = pending_outbound or []
    broker.accepted_proposals.return_value = list(accepted or [])
    broker.quarantined_proposals.return_value = list(quarantined or [])
    return broker


def _make_matrix() -> MagicMock:
    return MagicMock()


def _make_bridge(
    broker=None,
    matrix=None,
    audit_events: Optional[List] = None,
    chain_digest: str = "sha256:" + "c" * 64,
    source_repo_id: str = "adaad-core",
) -> EvolutionFederationBridge:
    if audit_events is None:
        audit_events = []

    def _ledger_append(event_type, payload):
        audit_events.append({"event_type": event_type, "payload": payload})

    return EvolutionFederationBridge(
        broker=broker or _make_broker(),
        evidence_matrix=matrix or _make_matrix(),
        ledger_append_event=_ledger_append,
        chain_digest_fn=lambda _: chain_digest,
        source_repo_id=source_repo_id,
    )


# ---------------------------------------------------------------------------
# BridgeResult.to_dict()
# ---------------------------------------------------------------------------
class TestBridgeResult:
    def test_to_dict_contains_all_fields(self):
        r = BridgeResult(
            hook="test_hook",
            epoch_id="epoch-1",
            ok=True,
            outbound_proposed=2,
            inbound_evaluated=3,
            inbound_accepted=2,
            inbound_quarantined=1,
            evidence_registered=True,
            error=None,
            detail={"extra": "data"},
        )
        d = r.to_dict()
        assert d["hook"] == "test_hook"
        assert d["epoch_id"] == "epoch-1"
        assert d["ok"] is True
        assert d["outbound_proposed"] == 2
        assert d["inbound_evaluated"] == 3
        assert d["inbound_accepted"] == 2
        assert d["inbound_quarantined"] == 1
        assert d["evidence_registered"] is True
        assert d["error"] is None
        assert d["detail"] == {"extra": "data"}

    def test_default_values(self):
        r = BridgeResult(hook="h", epoch_id="e", ok=False)
        d = r.to_dict()
        assert d["outbound_proposed"] == 0
        assert d["inbound_evaluated"] == 0
        assert d["inbound_accepted"] == 0
        assert d["inbound_quarantined"] == 0
        assert d["evidence_registered"] is False
        assert d["error"] is None
        assert d["detail"] == {}


# ---------------------------------------------------------------------------
# on_mutation_cycle_end
# ---------------------------------------------------------------------------
class TestOnMutationCycleEnd:
    def test_happy_path_returns_ok(self):
        proposal = _make_proposal(proposal_id="prop-xyz")
        broker = _make_broker()
        broker.propose_federated_mutation.return_value = proposal
        audit_events: List = []
        bridge = _make_bridge(broker=broker, audit_events=audit_events)

        result = bridge.on_mutation_cycle_end(
            epoch_id="epoch-1",
            mutation_id="mut-001",
            mutation_payload={"patch": "data"},
            gate_decision_payload={"approved": True},
        )

        assert result.ok is True
        assert result.hook == "on_mutation_cycle_end"
        assert result.outbound_proposed == 1
        assert result.detail["proposal_id"] == "prop-xyz"
        assert result.error is None

    def test_broker_called_with_correct_args(self):
        proposal = _make_proposal(proposal_id="prop-abc")
        broker = _make_broker()
        broker.propose_federated_mutation.return_value = proposal
        bridge = _make_bridge(broker=broker)

        bridge.on_mutation_cycle_end(
            epoch_id="epoch-2",
            mutation_id="mut-002",
            mutation_payload={"k": "v"},
            gate_decision_payload={"approved": True, "score": 0.9},
            destination_repo_id="repo-b",
        )

        call_kwargs = broker.propose_federated_mutation.call_args.kwargs
        assert call_kwargs["source_epoch_id"] == "epoch-2"
        assert call_kwargs["source_mutation_id"] == "mut-002"
        assert call_kwargs["mutation_payload"] == {"k": "v"}
        assert call_kwargs["gate_decision_payload"] == {"approved": True, "score": 0.9}
        assert call_kwargs["destination_repo_id"] == "repo-b"

    def test_default_destination_is_broadcast(self):
        proposal = _make_proposal()
        broker = _make_broker()
        broker.propose_federated_mutation.return_value = proposal
        bridge = _make_bridge(broker=broker)

        bridge.on_mutation_cycle_end(
            epoch_id="epoch-1",
            mutation_id="mut-001",
            mutation_payload={},
            gate_decision_payload={"approved": True},
        )

        call_kwargs = broker.propose_federated_mutation.call_args.kwargs
        assert call_kwargs["destination_repo_id"] == "broadcast"

    def test_audit_event_emitted_on_success(self):
        proposal = _make_proposal(proposal_id="prop-audit")
        broker = _make_broker()
        broker.propose_federated_mutation.return_value = proposal
        audit_events: List = []
        bridge = _make_bridge(broker=broker, audit_events=audit_events)

        bridge.on_mutation_cycle_end(
            epoch_id="epoch-1",
            mutation_id="mut-001",
            mutation_payload={},
            gate_decision_payload={"approved": True},
        )

        assert any(e["event_type"] == "federation_bridge_outbound_proposed" for e in audit_events)

    def test_broker_error_returns_not_ok(self):
        broker = _make_broker()
        broker.propose_federated_mutation.side_effect = RuntimeError("broker_contract_violation")
        bridge = _make_bridge(broker=broker)

        result = bridge.on_mutation_cycle_end(
            epoch_id="epoch-1",
            mutation_id="mut-001",
            mutation_payload={},
            gate_decision_payload={"approved": True},
        )

        assert result.ok is False
        assert "broker_contract_violation" in result.error
        assert result.outbound_proposed == 0

    def test_broker_error_emits_error_audit_event(self):
        broker = _make_broker()
        broker.propose_federated_mutation.side_effect = RuntimeError("err")
        audit_events: List = []
        bridge = _make_bridge(broker=broker, audit_events=audit_events)

        bridge.on_mutation_cycle_end(
            epoch_id="epoch-1",
            mutation_id="mut-001",
            mutation_payload={},
            gate_decision_payload={"approved": True},
        )

        assert any(e["event_type"] == "federation_bridge_outbound_error" for e in audit_events)

    def test_audit_failure_does_not_block_outbound(self):
        proposal = _make_proposal()
        broker = _make_broker()
        broker.propose_federated_mutation.return_value = proposal

        def _bad_ledger(evt, payload):
            raise IOError("disk_full")

        bridge = EvolutionFederationBridge(
            broker=broker,
            evidence_matrix=_make_matrix(),
            ledger_append_event=_bad_ledger,
            chain_digest_fn=lambda _: _ZERO_HASH,
        )

        result = bridge.on_mutation_cycle_end(
            epoch_id="epoch-1",
            mutation_id="mut-001",
            mutation_payload={},
            gate_decision_payload={"approved": True},
        )

        # Audit failed but the bridge hook still returns ok (proposal was created)
        assert result.ok is True


# ---------------------------------------------------------------------------
# on_inbound_evaluation
# ---------------------------------------------------------------------------
class TestOnInboundEvaluation:
    def test_no_proposals_returns_ok_with_zeros(self):
        broker = _make_broker()
        broker.evaluate_inbound_proposals.return_value = None
        bridge = _make_bridge(broker=broker)

        result = bridge.on_inbound_evaluation(epoch_id="epoch-1")

        assert result.ok is True
        assert result.inbound_evaluated == 0
        assert result.inbound_accepted == 0
        assert result.inbound_quarantined == 0

    def test_counts_newly_accepted_proposals(self):
        acc1 = _make_accepted("prop-1")
        acc2 = _make_accepted("prop-2")
        broker = _make_broker()

        # Simulate: before evaluation = 0 accepted; after = 2 accepted
        call_count = [0]
        def accepted_side_effect():
            call_count[0] += 1
            if call_count[0] <= 1:
                return []  # before evaluate_inbound_proposals
            return [acc1, acc2]  # after

        broker.accepted_proposals.side_effect = accepted_side_effect
        broker.quarantined_proposals.return_value = []
        bridge = _make_bridge(broker=broker)

        result = bridge.on_inbound_evaluation(epoch_id="epoch-1")

        assert result.ok is True
        assert result.inbound_accepted == 2

    def test_counts_newly_quarantined_proposals(self):
        q1 = _make_quarantined("prop-1", "gate_rejected")
        broker = _make_broker()

        qcall = [0]
        def qside():
            qcall[0] += 1
            return [] if qcall[0] <= 1 else [q1]

        broker.quarantined_proposals.side_effect = qside
        broker.accepted_proposals.return_value = []
        bridge = _make_bridge(broker=broker)

        result = bridge.on_inbound_evaluation(epoch_id="epoch-1")

        assert result.inbound_quarantined == 1

    def test_evaluate_inbound_proposals_called(self):
        broker = _make_broker()
        bridge = _make_bridge(broker=broker)
        bridge.on_inbound_evaluation(epoch_id="epoch-1")
        broker.evaluate_inbound_proposals.assert_called_once()

    def test_broker_error_returns_not_ok(self):
        broker = _make_broker()
        broker.evaluate_inbound_proposals.side_effect = RuntimeError("broker_error")
        bridge = _make_bridge(broker=broker)

        result = bridge.on_inbound_evaluation(epoch_id="epoch-1")

        assert result.ok is False
        assert "broker_error" in result.error

    def test_audit_event_emitted_for_inbound_error(self):
        broker = _make_broker()
        broker.evaluate_inbound_proposals.side_effect = RuntimeError("err")
        audit_events: List = []
        bridge = _make_bridge(broker=broker, audit_events=audit_events)

        bridge.on_inbound_evaluation(epoch_id="epoch-1")

        assert any(e["event_type"] == "federation_bridge_inbound_error" for e in audit_events)


# ---------------------------------------------------------------------------
# on_epoch_rotation
# ---------------------------------------------------------------------------
class TestOnEpochRotation:
    def test_happy_path_registers_epoch(self):
        matrix = _make_matrix()
        bridge = _make_bridge(matrix=matrix, chain_digest="sha256:" + "d" * 64)

        result = bridge.on_epoch_rotation(epoch_id="epoch-5")

        assert result.ok is True
        assert result.evidence_registered is True
        matrix.record_local_epoch.assert_called_once_with("epoch-5", "sha256:" + "d" * 64)

    def test_explicit_chain_digest_overrides_fn(self):
        matrix = _make_matrix()
        bridge = _make_bridge(matrix=matrix, chain_digest="sha256:" + "f" * 64)
        explicit = "sha256:" + "e" * 64

        bridge.on_epoch_rotation(epoch_id="epoch-6", chain_digest=explicit)

        matrix.record_local_epoch.assert_called_once_with("epoch-6", explicit)

    def test_audit_event_emitted_on_registration(self):
        matrix = _make_matrix()
        audit_events: List = []
        bridge = _make_bridge(matrix=matrix, audit_events=audit_events)

        bridge.on_epoch_rotation(epoch_id="epoch-7")

        assert any(e["event_type"] == "federation_bridge_epoch_registered" for e in audit_events)

    def test_digest_conflict_returns_not_ok(self):
        matrix = _make_matrix()
        matrix.record_local_epoch.side_effect = LocalEpochDigestConflictError(
            "federated_evidence:local_epoch_digest_conflict"
        )
        bridge = _make_bridge(matrix=matrix)

        result = bridge.on_epoch_rotation(epoch_id="epoch-8")

        assert result.ok is False
        assert "conflict" in result.error

    def test_conflict_emits_audit_event(self):
        matrix = _make_matrix()
        matrix.record_local_epoch.side_effect = LocalEpochDigestConflictError("digest_conflict")
        audit_events: List = []
        bridge = _make_bridge(matrix=matrix, audit_events=audit_events)

        bridge.on_epoch_rotation(epoch_id="epoch-9")

        assert any(
            e["event_type"] == "federation_bridge_epoch_digest_conflict"
            for e in audit_events
        )

    def test_idempotent_reregistration_returns_ok(self):
        matrix = _make_matrix()
        matrix.record_local_epoch.side_effect = [
            None,
            EpochAlreadyRegisteredSameDigest("already registered same digest"),
        ]
        bridge = _make_bridge(matrix=matrix)

        bridge.on_epoch_rotation(epoch_id="epoch-10")
        result = bridge.on_epoch_rotation(epoch_id="epoch-10")

        assert result.ok is True
        assert result.evidence_registered is False
        assert result.detail.get("idempotent") is True

    def test_unexpected_error_returns_not_ok(self):
        matrix = _make_matrix()
        matrix.record_local_epoch.side_effect = RuntimeError("boom")
        bridge = _make_bridge(matrix=matrix)

        result = bridge.on_epoch_rotation(epoch_id="epoch-11")

        assert result.ok is False
        assert result.error == "boom"


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------
class TestAccessors:
    def test_pending_outbound_count(self):
        broker = _make_broker(pending_outbound=[_make_proposal(), _make_proposal()])
        bridge = _make_bridge(broker=broker)
        assert bridge.pending_outbound_count() == 2

    def test_accepted_count(self):
        broker = _make_broker(accepted=[_make_accepted(), _make_accepted(), _make_accepted()])
        bridge = _make_bridge(broker=broker)
        assert bridge.accepted_count() == 3

    def test_quarantined_count(self):
        broker = _make_broker(quarantined=[_make_quarantined()])
        bridge = _make_bridge(broker=broker)
        assert bridge.quarantined_count() == 1

    def test_broker_accessor_returns_broker(self):
        broker = _make_broker()
        bridge = _make_bridge(broker=broker)
        assert bridge.broker() is broker

    def test_evidence_matrix_accessor_returns_matrix(self):
        matrix = _make_matrix()
        bridge = _make_bridge(matrix=matrix)
        assert bridge.evidence_matrix() is matrix
