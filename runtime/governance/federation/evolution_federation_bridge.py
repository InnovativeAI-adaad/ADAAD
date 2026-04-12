# SPDX-License-Identifier: Apache-2.0
"""EvolutionFederationBridge — Phase 5 lifecycle integration point.

This module wires the ``FederationMutationBroker`` and ``FederatedEvidenceMatrix``
into the ``EvolutionRuntime`` lifecycle at three well-defined hooks:

Lifecycle hooks
---------------
``on_mutation_cycle_end(epoch_id, mutation_id, mutation_payload, gate_decision)``
    Called by EvolutionRuntime after a mutation is gate-approved locally.
    Packages the mutation for downstream propagation via the broker.

``on_inbound_evaluation(epoch_id)``
    Called by EvolutionRuntime at the end of each mutation cycle.
    Drains the broker's inbound queue, evaluates each proposal through the
    destination GovernanceGate, and emits audit events to the lineage ledger.

``on_epoch_rotation(epoch_id, chain_digest)``
    Called by EvolutionRuntime after each epoch rotation.
    Registers the new epoch in the FederatedEvidenceMatrix so it can be
    referenced during cross-repo verification.

Constitutional constraints
--------------------------
- Bridge never bypasses GovernanceGate — it delegates to broker for all gate logic.
- Bridge fails closed when the broker raises on a contract violation.
- Audit write failures are fail-open (never block lifecycle).
- Bridge is optional: if not attached to EvolutionRuntime it has zero side-effects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentinel: zero hash used when chain digest is unavailable
# ---------------------------------------------------------------------------
_ZERO_HASH = "sha256:" + "0" * 64


# ---------------------------------------------------------------------------
# BridgeResult — structured return type for each hook
# ---------------------------------------------------------------------------
@dataclass
class BridgeResult:
    """Immutable result returned from every bridge hook."""

    hook: str
    epoch_id: str
    ok: bool
    outbound_proposed: int = 0
    inbound_evaluated: int = 0
    inbound_accepted: int = 0
    inbound_quarantined: int = 0
    evidence_registered: bool = False
    error: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hook": self.hook,
            "epoch_id": self.epoch_id,
            "ok": self.ok,
            "outbound_proposed": self.outbound_proposed,
            "inbound_evaluated": self.inbound_evaluated,
            "inbound_accepted": self.inbound_accepted,
            "inbound_quarantined": self.inbound_quarantined,
            "evidence_registered": self.evidence_registered,
            "error": self.error,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# EvolutionFederationBridge
# ---------------------------------------------------------------------------
class EvolutionFederationBridge:
    """Bridge adapter between EvolutionRuntime lifecycle hooks and Phase 5 federation.

    Parameters
    ----------
    broker:
        ``FederationMutationBroker`` instance — manages all proposal routing.
    evidence_matrix:
        ``FederatedEvidenceMatrix`` instance — tracks cross-repo epoch digests.
    ledger_append_event:
        Callable matching ``LineageLedgerV2.append_event(event_type, payload)`` —
        used to write audit events without introducing a hard import cycle.
    chain_digest_fn:
        Callable(epoch_id: str) -> str — resolves the current chain digest for
        an epoch.  Defaults to returning ``_ZERO_HASH`` if not supplied.
    source_repo_id:
        Stable identifier for the local repository (e.g. ``"adaad-core"``).
    """

    def __init__(
        self,
        *,
        broker: Any,
        evidence_matrix: Any,
        ledger_append_event: Callable[[str, Dict[str, Any]], Any],
        chain_digest_fn: Optional[Callable[[str], str]] = None,
        source_repo_id: str = "local",
    ) -> None:
        self._broker = broker
        self._matrix = evidence_matrix
        self._ledger_append = ledger_append_event
        self._chain_digest_fn: Callable[[str], str] = chain_digest_fn or (
            lambda _epoch_id: _ZERO_HASH
        )
        self._source_repo_id = source_repo_id

    # ------------------------------------------------------------------
    # Hook 1: on_mutation_cycle_end
    # ------------------------------------------------------------------
    def on_mutation_cycle_end(
        self,
        *,
        epoch_id: str,
        mutation_id: str,
        mutation_payload: Dict[str, Any],
        gate_decision_payload: Dict[str, Any],
        destination_repo_id: Optional[str] = None,
    ) -> BridgeResult:
        """Package a locally-approved mutation for downstream federation.

        This hook is called *after* the local GovernanceGate has approved the
        mutation.  It delegates immediately to the broker; no gate re-evaluation
        occurs here.

        Parameters
        ----------
        epoch_id:
            Current epoch identifier.
        mutation_id:
            Unique identifier for the mutation.
        mutation_payload:
            The mutation content to propagate.
        gate_decision_payload:
            The serialized gate decision from the local GovernanceGate.
            Must contain ``{"approved": True, ...}`` — broker enforces this.
        destination_repo_id:
            Optional destination repo for directed propagation.  If None the
            proposal is marked for broadcast.
        """
        hook_name = "on_mutation_cycle_end"
        try:
            chain_digest = self._chain_digest_fn(epoch_id)
            proposal = self._broker.propose_federated_mutation(
                source_epoch_id=epoch_id,
                source_mutation_id=mutation_id,
                mutation_payload=mutation_payload,
                gate_decision_payload=gate_decision_payload,
                destination_repo_id=destination_repo_id or "broadcast",
                chain_digest_fn=lambda: chain_digest,
            )
            self._safe_audit(
                "federation_bridge_outbound_proposed",
                {
                    "epoch_id": epoch_id,
                    "mutation_id": mutation_id,
                    "proposal_id": proposal.proposal_id,
                    "destination_repo_id": destination_repo_id or "broadcast",
                },
            )
            return BridgeResult(
                hook=hook_name,
                epoch_id=epoch_id,
                ok=True,
                outbound_proposed=1,
                detail={"proposal_id": proposal.proposal_id},
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "federation_bridge.on_mutation_cycle_end failed: %s", exc, exc_info=True
            )
            self._safe_audit(
                "federation_bridge_outbound_error",
                {"epoch_id": epoch_id, "mutation_id": mutation_id, "error": str(exc)},
            )
            return BridgeResult(
                hook=hook_name,
                epoch_id=epoch_id,
                ok=False,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Hook 2: on_inbound_evaluation
    # ------------------------------------------------------------------
    def on_inbound_evaluation(self, *, epoch_id: str) -> BridgeResult:
        """Drain and evaluate all inbound federated proposals for the current epoch.

        Calls ``FederationMutationBroker.evaluate_inbound_proposals()``.  Each
        accepted proposal is logged to the lineage ledger via ``ledger_append_event``.
        Quarantined proposals are also logged.

        This hook is designed to be called at the *end* of each mutation cycle
        (after ``after_mutation_cycle``) so federation evaluation never blocks
        local mutation progress.
        """
        hook_name = "on_inbound_evaluation"
        try:
            pre_accepted = len(self._broker.accepted_proposals())
            pre_quarantined = len(self._broker.quarantined_proposals())

            self._broker.evaluate_inbound_proposals()

            post_accepted = len(self._broker.accepted_proposals())
            post_quarantined = len(self._broker.quarantined_proposals())

            raw_newly_accepted = post_accepted - pre_accepted
            raw_newly_quarantined = post_quarantined - pre_quarantined
            if raw_newly_accepted < 0 or raw_newly_quarantined < 0:
                logger.warning(
                    "federation_bridge.on_inbound_evaluation observed negative delta(s): "
                    "accepted=%s quarantined=%s (pre: accepted=%s quarantined=%s, "
                    "post: accepted=%s quarantined=%s). Possible broker list reset/compaction.",
                    raw_newly_accepted,
                    raw_newly_quarantined,
                    pre_accepted,
                    pre_quarantined,
                    post_accepted,
                    post_quarantined,
                )

            newly_accepted = max(0, raw_newly_accepted)
            newly_quarantined = max(0, raw_newly_quarantined)
            evaluated = newly_accepted + newly_quarantined

            # Emit per-accepted audit events
            accepted_list = self._broker.accepted_proposals()
            for accepted in accepted_list[-newly_accepted:] if newly_accepted else []:
                self._safe_audit(
                    "federation_bridge_inbound_accepted",
                    {
                        "epoch_id": epoch_id,
                        "proposal_id": accepted.proposal.proposal_id,
                        "source_repo": accepted.proposal.source_repo,
                        "source_epoch_id": accepted.proposal.source_epoch_id,
                        "acceptance_digest": accepted.acceptance_digest,
                    },
                )

            # Emit per-quarantined audit events
            quarantined_list = self._broker.quarantined_proposals()
            for quarantined in quarantined_list[-newly_quarantined:] if newly_quarantined else []:
                self._safe_audit(
                    "federation_bridge_inbound_quarantined",
                    {
                        "epoch_id": epoch_id,
                        "proposal_id": quarantined.get("proposal_id", "unknown"),
                        "reason": quarantined.get("reason", "unknown"),
                    },
                )

            return BridgeResult(
                hook=hook_name,
                epoch_id=epoch_id,
                ok=True,
                inbound_evaluated=evaluated,
                inbound_accepted=newly_accepted,
                inbound_quarantined=newly_quarantined,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "federation_bridge.on_inbound_evaluation failed: %s", exc, exc_info=True
            )
            self._safe_audit(
                "federation_bridge_inbound_error",
                {"epoch_id": epoch_id, "error": str(exc)},
            )
            return BridgeResult(
                hook=hook_name,
                epoch_id=epoch_id,
                ok=False,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Hook 3: on_epoch_rotation
    # ------------------------------------------------------------------
    def on_epoch_rotation(self, *, epoch_id: str, chain_digest: Optional[str] = None) -> BridgeResult:
        """Register a completed epoch in the FederatedEvidenceMatrix.

        Called by EvolutionRuntime after each epoch rotation.  Records the
        epoch's chain digest so it can be used as a verification anchor during
        cross-repo evidence matrix checks.

        Parameters
        ----------
        epoch_id:
            The epoch that just completed.
        chain_digest:
            The final chain digest for the epoch.  If None, resolved via
            ``chain_digest_fn``.
        """
        hook_name = "on_epoch_rotation"
        resolved_digest = chain_digest or self._chain_digest_fn(epoch_id)
        try:
            self._matrix.record_local_epoch(epoch_id, resolved_digest)
            self._safe_audit(
                "federation_bridge_epoch_registered",
                {
                    "epoch_id": epoch_id,
                    "chain_digest": resolved_digest,
                },
            )
            return BridgeResult(
                hook=hook_name,
                epoch_id=epoch_id,
                ok=True,
                evidence_registered=True,
                detail={"chain_digest": resolved_digest},
            )
        except Exception as exc:  # noqa: BLE001
            # Conflict (same epoch, different digest) is a hard error
            if "conflict" in str(exc).lower() or "digest_conflict" in str(exc).lower():
                logger.error(
                    "federation_bridge.on_epoch_rotation — epoch digest conflict: %s", exc
                )
                self._safe_audit(
                    "federation_bridge_epoch_digest_conflict",
                    {"epoch_id": epoch_id, "chain_digest": resolved_digest, "error": str(exc)},
                )
                return BridgeResult(
                    hook=hook_name,
                    epoch_id=epoch_id,
                    ok=False,
                    error=str(exc),
                    detail={"chain_digest": resolved_digest},
                )
            # Idempotent re-registration: already registered with same digest — OK
            logger.debug(
                "federation_bridge.on_epoch_rotation idempotent: epoch=%s", epoch_id
            )
            return BridgeResult(
                hook=hook_name,
                epoch_id=epoch_id,
                ok=True,
                evidence_registered=False,  # already registered
                detail={"chain_digest": resolved_digest, "idempotent": True},
            )

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    def pending_outbound_count(self) -> int:
        """Return the number of proposals waiting for transport flush."""
        return len(self._broker.pending_outbound())

    def accepted_count(self) -> int:
        """Return the total number of accepted inbound proposals."""
        return len(self._broker.accepted_proposals())

    def quarantined_count(self) -> int:
        """Return the total number of quarantined inbound proposals."""
        return len(self._broker.quarantined_proposals())

    def broker(self) -> Any:
        """Read-only access to the underlying broker (for transport flush)."""
        return self._broker

    def evidence_matrix(self) -> Any:
        """Read-only access to the underlying evidence matrix."""
        return self._matrix

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _safe_audit(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Emit an audit event; never re-raises (fail-open on audit)."""
        try:
            self._ledger_append(event_type, payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("federation_bridge audit write failed: %s", exc)
