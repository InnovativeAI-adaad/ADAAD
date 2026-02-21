# SPDX-License-Identifier: Apache-2.0
"""Evolution governor responsible for authorization and certification."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

from app.agents.mutation_request import MutationRequest
from runtime.evolution.checkpoint import checkpoint_digest
from runtime.evolution.impact import ImpactScorer
from runtime.evolution.lineage_v2 import EpochEndEvent, EpochStartEvent, LineageEvent, LineageLedgerV2
from runtime.evolution.mutation_budget import MutationBudgetDecision, MutationBudgetManager
from runtime.evolution.metrics_schema import EvolutionMetricsEmitter
from runtime.evolution.scoring import authority_threshold, clamp_score
from runtime.governance.deterministic_envelope import (
    EntropyBudgetExceeded,
    EntropySource,
    charge_entropy,
    deterministic_envelope,
    get_current_ledger,
)
from runtime.governance.foundation import RuntimeDeterminismProvider, default_provider, require_replay_safe_provider
from runtime.timeutils import now_iso
from security import cryovant


@dataclass(frozen=True)
class GovernanceDecision:
    accepted: bool
    reason: str
    certificate: Dict[str, Any] | None = None
    replay_status: str = "unknown"
    mutation_cost: float = 0.0
    fitness_gain: float = 0.0
    roi: float = 0.0


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

    def __init__(
        self,
        ledger: LineageLedgerV2 | None = None,
        impact_scorer: ImpactScorer | None = None,
        max_impact: float = 0.85,
        *,
        replay_mode: str = "off",
        provider: RuntimeDeterminismProvider | None = None,
        entropy_budget: int | None = None,
        mutation_budget_manager: MutationBudgetManager | None = None,
    ) -> None:
        sovereign_mode = os.getenv("ADAAD_SOVEREIGN_MODE", "").strip().lower()
        strict_sovereign_mode = sovereign_mode == "strict"

        if entropy_budget is not None:
            resolved_entropy_budget: int | str = entropy_budget
        else:
            env_entropy_budget = os.getenv("ADAAD_GOVERNOR_ENTROPY_BUDGET")
            if env_entropy_budget is None:
                if strict_sovereign_mode:
                    raise ValueError("entropy_budget_required_in_strict_sovereign_mode")
                resolved_entropy_budget = 100
            else:
                try:
                    resolved_entropy_budget = int(env_entropy_budget)
                except (TypeError, ValueError):
                    if strict_sovereign_mode:
                        raise ValueError("invalid_entropy_budget_in_strict_sovereign_mode")
                    resolved_entropy_budget = 100

        self.ledger = ledger or LineageLedgerV2()
        self.impact_scorer = impact_scorer or ImpactScorer()
        self.max_impact = max_impact
        self.replay_mode = replay_mode
        self.provider = provider or default_provider()
        self.fail_closed = False
        self.fail_closed_reason = ""
        self.recovery_tier = RecoveryTier.SOFT
        self.entropy_budget = max(0, int(resolved_entropy_budget))
        self.mutation_budget_manager = mutation_budget_manager or MutationBudgetManager(
            per_cycle_budget=float(os.getenv("ADAAD_MUTATION_PER_CYCLE_BUDGET", "100") or 100.0),
            per_epoch_budget=float(os.getenv("ADAAD_MUTATION_PER_EPOCH_BUDGET", "10000") or 10000.0),
            roi_threshold=float(os.getenv("ADAAD_MUTATION_MIN_ROI", "0.1") or 0.1),
            exploration_rate=float(os.getenv("ADAAD_MUTATION_EXPLORATION_RATE", "0.1") or 0.1),
            exploration_step=float(os.getenv("ADAAD_MUTATION_EXPLORATION_STEP", "0.05") or 0.05),
            min_exploration_rate=float(os.getenv("ADAAD_MUTATION_MIN_EXPLORATION", "0.0") or 0.0),
            max_exploration_rate=float(os.getenv("ADAAD_MUTATION_MAX_EXPLORATION", "0.5") or 0.5),
        )
        self.metrics_emitter = EvolutionMetricsEmitter(self.ledger)
        self._validation_lock = threading.RLock()
        # Strict-replay nonce ordering uses a dedicated plain Lock + Condition so
        # that Condition.wait() releases correctly.
        self._ordering_lock = threading.Lock()
        self._validation_order = threading.Condition(self._ordering_lock)
        self._epoch_next_nonce_index: Dict[str, int] = {}

    @staticmethod
    def _nonce_index(nonce: str) -> int | None:
        """Parse the trailing integer from a nonce of the form ``<prefix>-<int>``."""

        tail = (nonce or "").rsplit("-", 1)
        if len(tail) != 2 or not tail[1].isdigit():
            return None
        return int(tail[1])

    _STRICT_ORDER_TIMEOUT_S: float = 0.25
    _STRICT_ORDER_POLL_S: float = 0.005

    def _wait_for_strict_turn(self, epoch_id: str, request: MutationRequest) -> None:
        """Best-effort nonce-ordered serialisation for strict replay lanes."""

        if (self.replay_mode or "off").strip().lower() != "strict":
            return

        nonce_index = self._nonce_index(request.nonce)
        if nonce_index is None:
            from runtime import metrics as _metrics

            _metrics.log(
                event_type="strict_replay_malformed_nonce",
                payload={
                    "epoch_id": epoch_id,
                    "agent_id": request.agent_id,
                    "nonce": str(request.nonce or ""),
                    "reason": "malformed_nonce_index",
                },
                level="WARNING",
            )
            return

        deadline = self._STRICT_ORDER_TIMEOUT_S
        with self._validation_order:
            expected = self._epoch_next_nonce_index.setdefault(epoch_id, nonce_index)
            elapsed = 0.0
            while nonce_index != expected and elapsed < deadline:
                self._validation_order.wait(timeout=self._STRICT_ORDER_POLL_S)
                elapsed += self._STRICT_ORDER_POLL_S
                expected = self._epoch_next_nonce_index.get(epoch_id, nonce_index)

            if nonce_index != expected:
                from runtime import metrics as _metrics

                _metrics.log(
                    event_type="strict_replay_ordering_timeout",
                    payload={
                        "epoch_id": epoch_id,
                        "agent_id": request.agent_id,
                        "nonce": str(request.nonce or ""),
                        "nonce_index": nonce_index,
                        "expected_index": expected,
                        "waited_s": round(elapsed, 4),
                    },
                    level="WARNING",
                )

            self._epoch_next_nonce_index[epoch_id] = max(expected, nonce_index) + 1
            self._validation_order.notify_all()

    def validate_bundle(self, request: MutationRequest, epoch_id: str) -> GovernanceDecision:
        with self._validation_lock:
            self._wait_for_strict_turn(epoch_id, request)
            try:
                with deterministic_envelope(
                    epoch_id=epoch_id or "unknown",
                    budget=self.entropy_budget,
                    provider=self.provider,
                ) as entropy_ledger:
                    decision = self._validate_bundle_internal(request, epoch_id)
                    if decision.certificate:
                        decision.certificate["entropy_consumed"] = entropy_ledger.consumed
                        decision.certificate["entropy_budget"] = entropy_ledger.budget
                        decision.certificate["entropy_overflow"] = entropy_ledger.overflow
                    self._record_entropy_metrics(epoch_id, decision, entropy_ledger)
                    return decision
            except EntropyBudgetExceeded:
                decision = GovernanceDecision(accepted=False, reason="entropy_budget_exceeded", replay_status="failed")
                self._record_decision(request, epoch_id, decision, impact_score=0.0)
                ledger = get_current_ledger()
                if ledger is not None:
                    self._record_entropy_metrics(epoch_id, decision, ledger)
                return decision

    def _validate_bundle_internal(self, request: MutationRequest, epoch_id: str) -> GovernanceDecision:
        charge_entropy(EntropySource.PROVIDER, "governor_validate_bundle:start")
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

        charge_entropy(EntropySource.PROVIDER, "governor_validate_bundle:signature_check")
        if not cryovant.signature_valid(request.signature or ""):
            decision = GovernanceDecision(accepted=False, reason="invalid_signature")
            self._record_decision(request, epoch_id, decision, impact_score=0.0)
            return decision

        continuity_ok = bool(request.nonce and request.generation_ts)
        if not continuity_ok:
            decision = GovernanceDecision(accepted=False, reason="lineage_continuity_failed")
            self._record_decision(request, epoch_id, decision, impact_score=0.0)
            return decision

        charge_entropy(EntropySource.PROVIDER, "governor_validate_bundle:impact_score")
        impact = self.impact_scorer.score(request)
        impact_total = clamp_score(float(impact.total))
        if impact_total > self.max_impact:
            decision = GovernanceDecision(accepted=False, reason="impact_threshold_exceeded")
            self._record_decision(request, epoch_id, decision, impact_score=impact_total)
            return decision

        threshold = authority_threshold(request.authority_level or "")
        if impact_total > threshold:
            decision = GovernanceDecision(accepted=False, reason="authority_level_exceeded")
            self._record_decision(request, epoch_id, decision, impact_score=impact_total)
            return decision

        bundle_id = (request.bundle_id or "").strip() or self._deterministic_bundle_id(request=request, epoch_id=epoch_id)
        self._apply_metrics_feedback_loop(epoch_id=epoch_id)
        budget_decision = self._evaluate_mutation_budget(request, epoch_id, bundle_id, impact_total)
        if not budget_decision.accepted:
            decision = GovernanceDecision(
                accepted=False,
                reason=budget_decision.reason,
                replay_status="failed",
                mutation_cost=budget_decision.mutation_cost,
                fitness_gain=budget_decision.fitness_gain,
                roi=budget_decision.roi,
            )
            self._record_decision(request, epoch_id, decision, impact_score=impact_total)
            return decision

        certificate = self._issue_certificate(request, epoch_id, impact_total, bundle_id=bundle_id)
        certificate.update(
            {
                "mutation_cost": budget_decision.mutation_cost,
                "fitness_gain": budget_decision.fitness_gain,
                "roi": budget_decision.roi,
                "budget_threshold": budget_decision.threshold,
                "exploration_rate": budget_decision.exploration_rate,
            }
        )
        decision = GovernanceDecision(
            accepted=True,
            reason="accepted",
            certificate=certificate,
            replay_status="ok",
            mutation_cost=budget_decision.mutation_cost,
            fitness_gain=budget_decision.fitness_gain,
            roi=budget_decision.roi,
        )
        self._record_decision(request, epoch_id, decision, impact_score=impact_total)
        return decision


    def _apply_metrics_feedback_loop(self, *, epoch_id: str) -> None:
        history = self.metrics_emitter._read_history()
        budget_config_before = {
            "roi_threshold": float(self.mutation_budget_manager.roi_threshold),
            "per_cycle_budget": float(self.mutation_budget_manager.per_cycle_budget),
            "exploration_rate": float(self.mutation_budget_manager.exploration_rate),
        }
        feedback = self.mutation_budget_manager.ingest_rolling_metrics(history)

        acceptance_rate = float(feedback.get("acceptance_rate", 0.0) or 0.0)
        avg_entropy_utilization = float(feedback.get("avg_entropy_utilization", 0.0) or 0.0)
        cost_per_accepted = float(feedback.get("cost_per_accepted", 0.0) or 0.0)

        old_entropy_budget = int(self.entropy_budget)
        if acceptance_rate < 0.25:
            self.entropy_budget = max(10, int(self.entropy_budget * 0.95))
        elif avg_entropy_utilization < 0.20:
            self.entropy_budget = min(100_000, int(self.entropy_budget * 1.05))

        summary_path = self.metrics_emitter.metrics_dir / epoch_id / "summary.json"
        if summary_path.exists():
            try:
                summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                summary_payload = {}
            if bool(summary_payload.get("local_optima_risk", False)):
                self.mutation_budget_manager.exploration_rate = min(
                    self.mutation_budget_manager.max_exploration_rate,
                    self.mutation_budget_manager.exploration_rate + max(self.mutation_budget_manager.exploration_step, 0.1),
                )

        budget_config_after = {
            "roi_threshold": float(self.mutation_budget_manager.roi_threshold),
            "per_cycle_budget": float(self.mutation_budget_manager.per_cycle_budget),
            "exploration_rate": float(self.mutation_budget_manager.exploration_rate),
        }
        if budget_config_after != budget_config_before:
            self.ledger.append_event(
                "GovernorConfigEvent",
                {
                    "epoch_id": epoch_id,
                    "config_key": "mutation_budget_params",
                    "old_value": budget_config_before,
                    "new_value": budget_config_after,
                    "reason": "metrics_feedback_loop",
                    "ts": now_iso(),
                },
            )

        if int(self.entropy_budget) != old_entropy_budget:
            self.ledger.append_event(
                "GovernorConfigEvent",
                {
                    "epoch_id": epoch_id,
                    "config_key": "entropy_budget",
                    "old_value": old_entropy_budget,
                    "new_value": int(self.entropy_budget),
                    "reason": "metrics_feedback_loop",
                    "ts": now_iso(),
                },
            )

        from runtime import metrics

        metrics.log(
            event_type="governor_feedback_loop",
            payload={
                "epoch_id": epoch_id,
                "acceptance_rate": acceptance_rate,
                "avg_entropy_utilization": avg_entropy_utilization,
                "cost_per_accepted": cost_per_accepted,
                "entropy_budget": int(self.entropy_budget),
                "roi_threshold": float(self.mutation_budget_manager.roi_threshold),
                "per_cycle_budget": float(self.mutation_budget_manager.per_cycle_budget),
                "exploration_rate": float(self.mutation_budget_manager.exploration_rate),
            },
            level="INFO",
        )

    def _evaluate_mutation_budget(
        self,
        request: MutationRequest,
        epoch_id: str,
        bundle_id: str,
        impact_total: float,
    ) -> MutationBudgetDecision:
        runtime_cost = float(len(request.ops) + sum(len(target.ops) for target in request.targets))
        entropy_delta = float(max(0, int(request.random_seed != 0)))
        complexity_delta = float(max(0, len(request.targets) - 1))
        fitness_gain = max(0.0, 1.0 - impact_total)
        return self.mutation_budget_manager.evaluate(
            cycle_id=bundle_id,
            epoch_id=epoch_id,
            runtime_cost=runtime_cost,
            entropy_delta=entropy_delta,
            complexity_delta=complexity_delta,
            fitness_gain=fitness_gain,
        )

    def _record_entropy_metrics(self, epoch_id: str, decision: GovernanceDecision, ledger: Any) -> None:
        from runtime import metrics

        metrics.log(
            event_type="entropy_envelope_usage",
            payload={
                "epoch_id": epoch_id,
                "accepted": decision.accepted,
                "reason": decision.reason,
                "consumed": int(getattr(ledger, "consumed", 0) or 0),
                "budget": int(getattr(ledger, "budget", 0) or 0),
                "overflow": bool(getattr(ledger, "overflow", False)),
                "remaining": int(getattr(ledger, "remaining", lambda: 0)() or 0),
            },
            level="INFO",
        )

    def activate_certificate(self, epoch_id: str, bundle_id: str, activated: bool, reason: str) -> None:
        budget_decision = self.mutation_budget_manager.decision_for_cycle(bundle_id)
        if activated and budget_decision is not None and not budget_decision.accepted:
            activated = False
            reason = budget_decision.reason
        payload = {
            "epoch_id": epoch_id,
            "bundle_id": bundle_id,
            "certificate_activated": activated,
            "reason": reason,
            "mutation_cost": float((budget_decision.mutation_cost if budget_decision is not None else 0.0)),
            "fitness_gain": float((budget_decision.fitness_gain if budget_decision is not None else 0.0)),
            "roi": float((budget_decision.roi if budget_decision is not None else 0.0)),
            "accepted": bool(activated),
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
            "fail_closed": True,
            "reason": reason,
            "tier": tier.value,
            "decision": "fail_closed",
            "evidence": {"reason": reason, "tier": tier.value},
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
            "decision": "recovery_requested",
            "evidence": {"signature": recovery_signature},
        }
        if tier == RecoveryTier.CONSTITUTIONAL_RESET:
            self.fail_closed = False
            self.fail_closed_reason = ""
            payload["fail_closed"] = False
        self.recovery_tier = tier
        self.ledger.append_event("GovernanceDecisionEvent", payload)
        return tier == RecoveryTier.CONSTITUTIONAL_RESET

    def _issue_certificate(self, request: MutationRequest, epoch_id: str, impact_score: float, *, bundle_id: str | None = None) -> Dict[str, Any]:
        requested_bundle_id = (request.bundle_id or "").strip()
        require_replay_safe_provider(
            self.provider,
            replay_mode=self.replay_mode,
            recovery_tier=self.recovery_tier.value,
        )
        resolved_bundle_id = bundle_id or requested_bundle_id or self._deterministic_bundle_id(request=request, epoch_id=epoch_id)
        replay_seed = self._replay_seed(request=request, epoch_id=epoch_id, bundle_id=resolved_bundle_id)
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
            "bundle_id": resolved_bundle_id,
            "bundle_id_source": "request" if requested_bundle_id else "governor",
            "strategy_set": strategy_set,
            "strategy_version_set": strategy_version_set,
            "strategy_snapshot": strategy_snapshot,
            "strategy_snapshot_hash": strategy_snapshot_hash,
            "strategy_hash": strategy_snapshot_hash,
            "impact_score": impact_score,
            "checkpoint_digest": self.ledger.get_epoch_digest(epoch_id)
            or checkpoint_digest({"epoch_id": epoch_id, "empty": True}),
            "authority_signatures": [request.signature],
            "certificate_activated": False,
            "replay_seed": replay_seed,
        }

    def _replay_seed(self, *, request: MutationRequest, epoch_id: str, bundle_id: str) -> str:
        """Return a 16-hex replay seed that never uses the all-zero sentinel.

        In replay-safe contexts this is deterministic from stable inputs.
        """
        source = f"{epoch_id}|{bundle_id}|{request.agent_id}|{request.intent or ''}|{request.nonce or ''}"
        seed = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
        return seed if seed != "0" * 16 else "0" * 15 + "1"

    def _deterministic_bundle_id(self, *, request: MutationRequest, epoch_id: str) -> str:
        material = f"{epoch_id}|{request.agent_id}|{request.intent or ''}|{request.nonce or ''}|{request.generation_ts or ''}"
        return f"bundle-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"

    def _record_decision(self, request: MutationRequest, epoch_id: str, decision: GovernanceDecision, impact_score: float) -> None:
        payload: Dict[str, Any] = {
            "epoch_id": epoch_id,
            "agent_id": request.agent_id,
            "intent": request.intent,
            "accepted": decision.accepted,
            "reason": decision.reason,
            "mutation_cost": decision.mutation_cost,
            "fitness_gain": decision.fitness_gain,
            "roi": decision.roi,
            "impact_score": impact_score,
            "replay_status": decision.replay_status,
        }
        entropy_ledger = get_current_ledger()
        if entropy_ledger is not None:
            payload["entropy_consumed"] = entropy_ledger.consumed
            payload["entropy_budget"] = entropy_ledger.budget
            payload["entropy_overflow"] = entropy_ledger.overflow

        if decision.certificate:
            payload["certificate"] = decision.certificate
            payload["bundle_id"] = decision.certificate.get("bundle_id")
            payload["impact"] = impact_score
            payload["strategy_set"] = decision.certificate.get("strategy_set", [])
            self.ledger.append_bundle_with_digest(epoch_id, payload)
        else:
            self.ledger.append(LineageEvent("GovernanceDecisionEvent", payload))

        from runtime import metrics

        metrics.log(
            event_type="governance_mutation_budget_decision",
            payload={
                "epoch_id": epoch_id,
                "agent_id": request.agent_id,
                "accepted": decision.accepted,
                "reason": decision.reason,
                "mutation_cost": decision.mutation_cost,
                "fitness_gain": decision.fitness_gain,
                "roi": decision.roi,
            },
            level="INFO" if decision.accepted else "WARNING",
        )

    def _epoch_started(self, epoch_id: str) -> bool:
        epoch_events = self.ledger.read_epoch(epoch_id)
        has_start = any(e.get("type") == "EpochStartEvent" for e in epoch_events)
        has_end = any(e.get("type") == "EpochEndEvent" for e in epoch_events)
        return has_start and not has_end


__all__ = ["EvolutionGovernor", "GovernanceDecision", "RecoveryTier"]
