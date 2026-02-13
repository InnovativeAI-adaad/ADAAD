# SPDX-License-Identifier: Apache-2.0
"""Evolution governor responsible for authorization and certification."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

from app.agents.mutation_request import MutationRequest
from runtime.evolution.impact import ImpactScorer
from runtime.evolution.lineage_v2 import EpochEndEvent, EpochStartEvent, LineageEvent, LineageLedgerV2
from runtime.timeutils import now_iso
from security import cryovant


@dataclass(frozen=True)
class GovernanceDecision:
    accepted: bool
    reason: str
    certificate: Dict[str, Any] | None = None
    replay_status: str = "unknown"


class RecoveryTier(Enum):
    SOFT = "soft"
    AUDIT = "audit"
    CONSTITUTIONAL_RESET = "constitutional_reset"


class EvolutionGovernor:
    AUTHORITY_MATRIX = {
        "low-impact": 0.20,
        "governor-review": 0.50,
        "high-impact": 1.00,
    }

    def __init__(self, ledger: LineageLedgerV2 | None = None, impact_scorer: ImpactScorer | None = None, max_impact: float = 0.85) -> None:
        self.ledger = ledger or LineageLedgerV2()
        self.impact_scorer = impact_scorer or ImpactScorer()
        self.max_impact = max_impact
        self.fail_closed = False
        self.fail_closed_reason = ""
        self.recovery_tier = RecoveryTier.SOFT

    def validate_bundle(self, request: MutationRequest, epoch_id: str) -> GovernanceDecision:
        if self.fail_closed:
            decision = GovernanceDecision(accepted=False, reason="governor_fail_closed", replay_status="failed")
            self._record_decision(request, epoch_id, decision, impact_score=0.0)
            return decision

        if not request.targets and not request.ops:
            return GovernanceDecision(accepted=False, reason="empty_bundle")

        if not epoch_id:
            decision = GovernanceDecision(accepted=False, reason="missing_epoch")
            self._record_decision(request, epoch_id, decision, impact_score=0.0)
            return decision
        if not self._epoch_started(epoch_id):
            decision = GovernanceDecision(accepted=False, reason="epoch_not_started")
            self._record_decision(request, epoch_id, decision, impact_score=0.0)
            return decision

        if not cryovant.signature_valid(request.signature or ""):
            decision = GovernanceDecision(accepted=False, reason="invalid_signature")
            self._record_decision(request, epoch_id, decision, impact_score=0.0)
            return decision

        continuity_ok = bool(request.nonce and request.generation_ts)
        if not continuity_ok:
            decision = GovernanceDecision(accepted=False, reason="lineage_continuity_failed")
            self._record_decision(request, epoch_id, decision, impact_score=0.0)
            return decision

        impact = self.impact_scorer.score(request)
        impact_total = min(max(float(impact.total), 0.0), 1.0)
        if impact_total > self.max_impact:
            decision = GovernanceDecision(accepted=False, reason="impact_threshold_exceeded")
            self._record_decision(request, epoch_id, decision, impact_score=impact_total)
            return decision

        threshold = self.AUTHORITY_MATRIX.get(request.authority_level or "", 0.0)
        if impact_total > threshold:
            decision = GovernanceDecision(accepted=False, reason="authority_level_exceeded")
            self._record_decision(request, epoch_id, decision, impact_score=impact_total)
            return decision

        certificate = self._issue_certificate(request, epoch_id, impact_total)
        decision = GovernanceDecision(accepted=True, reason="accepted", certificate=certificate, replay_status="ok")
        self._record_decision(request, epoch_id, decision, impact_score=impact_total)
        return decision

    def activate_certificate(self, epoch_id: str, bundle_id: str, activated: bool, reason: str) -> None:
        payload = {
            "epoch_id": epoch_id,
            "bundle_id": bundle_id,
            "certificate_activated": activated,
            "reason": reason,
        }
        self.ledger.append_event("CertificateActivationEvent", payload)

    def mark_epoch_start(self, epoch_id: str, metadata: Dict[str, Any] | None = None) -> None:
        self.ledger.append_typed_event(EpochStartEvent(epoch_id=epoch_id, ts=now_iso(), metadata=metadata or {}))

    def mark_epoch_end(self, epoch_id: str, metadata: Dict[str, Any] | None = None) -> None:
        self.ledger.append_typed_event(EpochEndEvent(epoch_id=epoch_id, ts=now_iso(), metadata=metadata or {}))

    def enter_fail_closed(self, reason: str, epoch_id: str, tier: RecoveryTier = RecoveryTier.SOFT) -> None:
        self.fail_closed = True
        self.fail_closed_reason = reason
        self.recovery_tier = tier
        payload = {
            "epoch_id": epoch_id,
            "reason": reason,
            "fail_closed": True,
            "recovery_tier": tier.value,
        }
        self.ledger.append_event("GovernanceDecisionEvent", payload)

    def apply_recovery_event(self, epoch_id: str, recovery_signature: str, tier: RecoveryTier) -> bool:
        if not recovery_signature.startswith("human-recovery-"):
            return False
        payload = {
            "epoch_id": epoch_id,
            "recovery_signature": recovery_signature,
            "requested_tier": tier.value,
            "fail_closed": True,
        }
        if tier == RecoveryTier.CONSTITUTIONAL_RESET:
            self.fail_closed = False
            self.fail_closed_reason = ""
            payload["fail_closed"] = False
        self.recovery_tier = tier
        self.ledger.append_event("GovernanceDecisionEvent", payload)
        return tier == RecoveryTier.CONSTITUTIONAL_RESET

    def _issue_certificate(self, request: MutationRequest, epoch_id: str, impact_score: float) -> Dict[str, Any]:
        requested_bundle_id = (request.bundle_id or "").strip()
        bundle_id = requested_bundle_id or uuid.uuid4().hex
        strategy_set: List[str] = [request.intent or "default"]
        strategy_version_set = [f"{request.intent or 'default'}:current"]
        strategy_snapshot = {
            request.intent or "default": {
                "version": "current",
                "hash": hashlib.sha256((request.intent or "default").encode("utf-8")).hexdigest(),
                "skill_weights": {},
            }
        }
        strategy_snapshot_hash = hashlib.sha256(
            json.dumps(strategy_snapshot, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return {
            "epoch_id": epoch_id,
            "bundle_id": bundle_id,
            "bundle_id_source": "request" if requested_bundle_id else "governor",
            "strategy_set": strategy_set,
            "strategy_version_set": strategy_version_set,
            "strategy_snapshot": strategy_snapshot,
            "strategy_snapshot_hash": strategy_snapshot_hash,
            "strategy_hash": strategy_snapshot_hash,
            "impact_score": impact_score,
            "checkpoint_digest": self.ledger.get_epoch_digest(epoch_id) or "sha256:0",
            "authority_signatures": [request.signature],
            "certificate_activated": False,
        }

    def _record_decision(self, request: MutationRequest, epoch_id: str, decision: GovernanceDecision, impact_score: float) -> None:
        payload: Dict[str, Any] = {
            "epoch_id": epoch_id,
            "agent_id": request.agent_id,
            "intent": request.intent,
            "accepted": decision.accepted,
            "reason": decision.reason,
            "impact_score": impact_score,
            "replay_status": decision.replay_status,
        }
        if decision.certificate:
            payload["certificate"] = decision.certificate
            payload["bundle_id"] = decision.certificate.get("bundle_id")
            payload["impact"] = impact_score
            payload["strategy_set"] = decision.certificate.get("strategy_set", [])
            self.ledger.append_bundle_with_digest(epoch_id, payload)
        else:
            self.ledger.append(LineageEvent("GovernanceDecisionEvent", payload))

    def _epoch_started(self, epoch_id: str) -> bool:
        epoch_events = self.ledger.read_epoch(epoch_id)
        has_start = any(e.get("type") == "EpochStartEvent" for e in epoch_events)
        has_end = any(e.get("type") == "EpochEndEvent" for e in epoch_events)
        return has_start and not has_end


__all__ = ["EvolutionGovernor", "GovernanceDecision", "RecoveryTier"]
