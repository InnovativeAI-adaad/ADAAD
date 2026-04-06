# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from app.api.schemas.dork_intents import (
    DorkEvidenceRef,
    DorkExecutionMarker,
    DorkIntentBundle,
    DorkIntentDecision,
    DorkIntentRouteRequest,
)
from app.orchestration.mutation_orchestration_service import MutationOrchestrationService
from runtime.api.runtime_services import governance_health_service, reviewer_calibration_service
from runtime.dork_event_stream import DorkEventStream
from runtime.governance.human_approval_gate import HumanApprovalGate
from runtime.oracle_ledger import OracleLedger
from runtime.snapshot_delta import SnapshotDeltaInterpreter
from runtime.system_status import read_gate_state


class DorkIntentRouter:
    """Map natural-language Dork queries to typed, safe intents."""

    _ORDERED_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("open_oracle_history", ("oracle", "history")),
        ("prepare_mutation_review", ("mutation", "review", "approval", "trigger")),
        ("explain_blockers", ("blocker", "blocked", "why", "failing", "fail")),
        ("show_gate_status", ("gate", "status", "tier", "health", "replay")),
        ("interpret_epoch_delta", ("what changed", "changed since", "last epoch", "delta", "difference")),
        ("generate_governance_brief", ("brief", "summary", "governance", "executive", "focus")),
    )

    def route(self, request: DorkIntentRouteRequest) -> DorkIntentDecision:
        normalized = " ".join(request.query.lower().split())
        for intent, keywords in self._ORDERED_RULES:
            if any(keyword in normalized for keyword in keywords):
                return DorkIntentDecision(
                    intent=intent,
                    normalized_query=normalized,
                    rationale=f"matched_keywords:{','.join(keywords)}",
                    marker=self._marker_for_intent(intent),
                )
        return DorkIntentDecision(
            intent="generate_governance_brief",
            normalized_query=normalized,
            rationale="fallback:governance_brief",
            marker=self._marker_for_intent("generate_governance_brief"),
        )

    @staticmethod
    def _marker_for_intent(intent: str) -> DorkExecutionMarker:
        actionable = intent in {"prepare_mutation_review"}
        return DorkExecutionMarker(advisory_only=not actionable, actionable_next_step=actionable)


class DorkIntentExecutor:
    """Execute routed intents against orchestration/runtime surfaces."""

    def __init__(self, *, event_stream: DorkEventStream | None = None) -> None:
        self._event_stream = event_stream or DorkEventStream()
        self._mutation_service = MutationOrchestrationService()
        self._approval_gate = HumanApprovalGate()
        self._oracle_ledger = OracleLedger()
        self._delta_interpreter = SnapshotDeltaInterpreter()

    @staticmethod
    def _digest_bundle(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(canonical.encode("utf-8")).hexdigest()

    def execute(self, *, request: DorkIntentRouteRequest, decision: DorkIntentDecision) -> DorkIntentBundle:
        response, evidence_refs, summary, panels = self._dispatch(intent=decision.intent, request=request)
        bundle_payload = {
            "intent": decision.intent,
            "marker": decision.marker.model_dump(),
            "response": response,
            "evidence_refs": [ref.model_dump() for ref in evidence_refs],
            "aponi_panels": panels,
        }
        bundle_digest = self._digest_bundle(bundle_payload)
        self._event_stream.append(
            intent=decision.intent,
            query=decision.normalized_query,
            bundle_digest=bundle_digest,
            marker=decision.marker.model_dump(),
            evidence_refs=[f"{ref.source}:{ref.endpoint}" for ref in evidence_refs],
        )
        if decision.intent == "interpret_epoch_delta":
            interpretation_payload = response.get("interpretation") if isinstance(response, dict) else None
            if isinstance(interpretation_payload, dict):
                self._event_stream.append_snapshot_interpretation(
                    query=decision.normalized_query,
                    before_snapshot=request.before_snapshot or {},
                    after_snapshot=request.after_snapshot or {},
                    interpretation=interpretation_payload,
                    bundle_digest=bundle_digest,
                )
        return DorkIntentBundle(
            intent=decision.intent,
            marker=decision.marker,
            summary=summary,
            response=response,
            evidence_refs=evidence_refs,
            aponi_panels=panels,
            bundle_digest=bundle_digest,
        )

    def _dispatch(self, *, intent: str, request: DorkIntentRouteRequest) -> tuple[dict[str, Any], list[DorkEvidenceRef], str, list[str]]:
        epoch_id = request.epoch_id.strip() or "epoch-dork"
        if intent == "show_gate_status":
            gate = read_gate_state()
            health = governance_health_service(epoch_id=epoch_id)
            response = {
                "gate_locked": bool(gate.get("locked", True)),
                "gate_source": str(gate.get("source", "unknown")),
                "gate_reason": str(gate.get("reason") or ""),
                "health_status": str(health.get("status", "unknown")),
                "health_score": float(health.get("health_score", 0.0)),
                "review_pressure": dict(health.get("review_pressure") or {}),
            }
            return response, [
                DorkEvidenceRef(source="runtime.system_status.read_gate_state", endpoint="/api/governance/status", panel="/ui/aponi/index.html"),
                DorkEvidenceRef(source="runtime.api.runtime_services.governance_health_service", endpoint="/api/governance/health", panel="/ui/developer/ADAADdev/whaledic.html"),
            ], "Gate status and governance health snapshot prepared.", ["/ui/aponi/index.html", "/ui/developer/ADAADdev/whaledic.html"]

        if intent == "explain_blockers":
            gate = read_gate_state()
            pending = self._approval_gate.pending_queue()
            blockers: list[str] = []
            if gate.get("locked"):
                blockers.append("governance_gate_locked")
            if pending:
                blockers.append("pending_human_approvals")
            response = {
                "blocker_count": len(blockers),
                "blockers": blockers,
                "pending_approvals": len(pending),
                "next_step": "Resolve gate lock reason and clear pending human approvals." if blockers else "No active blockers.",
            }
            return response, [
                DorkEvidenceRef(source="runtime.system_status.read_gate_state", endpoint="/api/governance/status", panel="/ui/aponi/index.html"),
                DorkEvidenceRef(source="runtime.governance.human_approval_gate.HumanApprovalGate.pending_queue", endpoint="/api/governance/approvals/pending", panel="/ui/aponi/index.html"),
            ], "Current blockers and immediate remediation path generated.", ["/ui/aponi/index.html"]

        if intent == "prepare_mutation_review":
            transition = self._mutation_service.choose_transition(
                mutation_enabled=True,
                fail_closed=bool(read_gate_state().get("locked")),
                governance_gate_passed=not bool(read_gate_state().get("locked")),
                exit_after_boot=False,
            )
            pending = self._approval_gate.pending_queue()
            response = {
                "transition": transition.to_dict(),
                "pending_approvals": len(pending),
                "actionable_next_step": "Use /api/governance/approvals/pending and /api/mutations/trigger-epoch once approvals are complete.",
            }
            return response, [
                DorkEvidenceRef(source="app.orchestration.mutation_orchestration_service.MutationOrchestrationService.choose_transition", endpoint="/api/mutations/trigger-epoch", panel="/ui/aponi/index.html"),
                DorkEvidenceRef(source="runtime.governance.human_approval_gate.HumanApprovalGate.pending_queue", endpoint="/api/governance/approvals/pending", panel="/ui/aponi/index.html"),
            ], "Mutation review packet prepared with actionable next step.", ["/ui/aponi/index.html"]


        if intent == "interpret_epoch_delta":
            before_snapshot = request.before_snapshot or {}
            after_snapshot = request.after_snapshot or {}
            if not after_snapshot:
                after_snapshot = {
                    "governance": read_gate_state(),
                    "replay": {},
                    "readiness": {},
                    "mutation": {},
                }
            interpretation = self._delta_interpreter.interpret(before=before_snapshot, after=after_snapshot)
            response = {
                "interpretation": interpretation.to_dict(),
                "card": {
                    "title": "What changed since last epoch?",
                    "risk_level": interpretation.risk_level,
                    "impacted_subsystems": interpretation.impacted_subsystems,
                    "likely_operator_actions": interpretation.likely_operator_actions[:3],
                    "confidence_score": interpretation.confidence_score,
                    "summary": interpretation.summary,
                },
            }
            return response, [
                DorkEvidenceRef(source="runtime.snapshot_delta.SnapshotDeltaInterpreter", endpoint="/api/dork/intents/route", panel="/ui/developer/ADAADdev/whaledic.html"),
            ], "Semantic delta interpretation prepared for latest epoch transition.", ["/ui/developer/ADAADdev/whaledic.html"]

        if intent == "open_oracle_history":
            records = self._oracle_ledger.replay(limit=request.limit)
            response = {
                "record_count": len(records),
                "ledger_path": str(self._oracle_ledger.path),
                "records": records,
            }
            return response, [
                DorkEvidenceRef(source="runtime.oracle_ledger.OracleLedger.replay", endpoint="/innovations/oracle/history", panel="/ui/aponi/index.html"),
            ], "Oracle history bundle loaded from deterministic ledger replay.", ["/ui/aponi/index.html"]

        health = governance_health_service(epoch_id=epoch_id)
        calibration = reviewer_calibration_service(epoch_id=epoch_id)
        response = {
            "epoch_id": epoch_id,
            "health_status": str(health.get("status", "unknown")),
            "health_score": float(health.get("health_score", 0.0)),
            "tier_pressure": str(calibration.get("tier_pressure", "nominal")),
            "cohort_summary": dict(calibration.get("cohort_summary") or {}),
            "focus": "Prioritize governance blockers, then continue approved mutation execution.",
        }
        return response, [
            DorkEvidenceRef(source="runtime.api.runtime_services.governance_health_service", endpoint="/api/governance/health", panel="/ui/developer/ADAADdev/whaledic.html"),
            DorkEvidenceRef(source="runtime.api.runtime_services.reviewer_calibration_service", endpoint="/api/governance/reviewer-calibration", panel="/ui/aponi/index.html"),
        ], "Governance brief assembled from runtime health and reviewer calibration.", ["/ui/developer/ADAADdev/whaledic.html", "/ui/aponi/index.html"]


__all__ = ["DorkIntentExecutor", "DorkIntentRouter"]
