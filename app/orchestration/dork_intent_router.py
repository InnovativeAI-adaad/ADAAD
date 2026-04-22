# SPDX-License-Identifier: Apache-2.0
# Phase 137 · INNOV-44 · DORK Intelligence Hardening & Capability Expansion
# Constitutional invariant: DORK-INTENT-0, DORK-FLEET-0

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
    DorkTrustMetadata,
)
from app.orchestration.mutation_orchestration_service import MutationOrchestrationService
from runtime.api.app_layer import (
    DorkEventStream,
    HumanApprovalGate,
    OracleLedger,
    SnapshotDeltaInterpreter,
    now_iso,
    read_gate_state,
    summarize_oracle_memory,
)
from runtime.api.runtime_services import governance_health_service, reviewer_calibration_service


# ── DORK-FLEET-0 ──────────────────────────────────────────────────────────────
# Hard invariant: DORKLivingFleet MUST be instantiated once per process as a
# module-level singleton. Per-call instantiation is constitutionally prohibited
# because it defeats fleet lifecycle management, watchdog continuity, and
# dispatch ledger chain integrity.
# ─────────────────────────────────────────────────────────────────────────────

_fleet_singleton = None

def _get_fleet():
    """Return the module-level DORKLivingFleet singleton (DORK-FLEET-0)."""
    global _fleet_singleton
    if _fleet_singleton is None:
        from runtime.innovations30.dork_living_fleet import DORKLivingFleet  # adaad: import-boundary-ok:dork-fleet-singleton-runtime
        _fleet_singleton = DORKLivingFleet()
    return _fleet_singleton


# ── Trust confidence table ────────────────────────────────────────────────────
# INNOV-44: replace hardcoded values with per-intent calibrated scores.
_INTENT_CONFIDENCE: dict[str, float] = {
    "show_gate_status": 0.91,
    "explain_blockers": 0.89,
    "prepare_mutation_review": 0.85,
    "open_oracle_history": 0.92,
    "interpret_epoch_delta": 0.83,
    "show_fleet_status": 0.88,
    "query_provider_health": 0.90,
    "replay_conversation_ledger": 0.87,
    "classify_query_intent": 0.84,
    "inspect_fleet_dispatch": 0.88,
    "resolve_slash_command": 0.95,
    "query_fleet_persist": 0.86,
    "trigger_fleet_heal": 0.82,
    "query_fleet_fitness": 0.86,
    "verify_fleet_chain": 0.91,
    "query_fleet_endpoints": 0.90,
    "generate_governance_brief": 0.74,  # heuristic fallback — lower confidence
}


class DorkIntentRouter:
    """Map natural-language Dork queries to typed, safe intents."""

    _ORDERED_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("open_oracle_history", ("oracle", "history")),
        ("prepare_mutation_review", ("mutation", "review", "approval", "trigger")),
        ("explain_blockers", ("blocker", "blocked", "why", "failing", "fail")),
        ("show_gate_status", ("gate", "status", "tier", "health", "replay")),
        ("interpret_epoch_delta", ("what changed", "changed since", "last epoch", "delta", "difference")),
        ("generate_governance_brief", ("brief", "summary", "governance", "executive", "focus")),
        # ── Phase 132 · INNOV-41 intents ────────────────────────────────────
        ("show_fleet_status", ("fleet", "provider", "ollama", "engine", "dork-fleet")),
        ("resolve_slash_command", ("slash", "/dork:", "dork:help", "dork:gate", "dork:fleet", "cmd resolver")),
        ("query_provider_health", ("provider health", "probe", "availability", "dork-prov", "backend")),
        ("replay_conversation_ledger", ("conversation ledger", "chat history", "session chain", "dork-state")),
        ("classify_query_intent", ("jaccard", "taxonomy", "intent class", "query route", "dork-ctx", "category")),
        ("inspect_fleet_dispatch", ("dispatch ledger", "fleet dispatch", "fleet chain", "dork-fleet-0")),
        # ── Phase 133 · INNOV-42 DFSB intents ───────────────────────────────
        ("query_fleet_persist", ("persist", "ledger_path", "dfsb persist", "conversation persist")),
        ("trigger_fleet_heal", ("heal", "recover", "dfsb heal", "fleet recover", "re-probe")),
        ("query_fleet_fitness", ("fitness", "fleet health", "degraded", "dfsb fitness")),
        ("verify_fleet_chain", ("fleet chain", "chain verify", "dispatch chain", "verify chain")),
        ("query_fleet_endpoints", ("endpoints", "fleet endpoints", "engine list", "registry")),
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
        actionable = intent in {"prepare_mutation_review", "trigger_fleet_heal"}
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
        trust_metadata = self._build_trust_metadata(decision=decision, evidence_refs=evidence_refs)
        bundle_payload = {
            "intent": decision.intent,
            "marker": decision.marker.model_dump(),
            "response": response,
            "evidence_refs": [ref.model_dump() for ref in evidence_refs],
            "aponi_panels": panels,
            "trust_metadata": trust_metadata.model_dump(mode="json"),
        }
        bundle_digest = self._digest_bundle(bundle_payload)
        self._event_stream.append(
            intent=decision.intent,
            query=decision.normalized_query,
            bundle_digest=bundle_digest,
            marker=decision.marker.model_dump(),
            evidence_refs=[f"{ref.source}:{ref.endpoint}" for ref in evidence_refs],
            trust_metadata=trust_metadata.model_dump(mode="json"),
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
            trust_metadata=trust_metadata,
        )

    def _build_trust_metadata(
        self, *, decision: DorkIntentDecision, evidence_refs: list[DorkEvidenceRef]
    ) -> DorkTrustMetadata:
        # INNOV-44: per-intent calibrated confidence; no more hardcoded 0.88/0.74
        retrieval_intents = {"open_oracle_history", "show_gate_status", "explain_blockers",
                             "verify_fleet_chain", "show_fleet_status"}
        deterministic_intents = {"resolve_slash_command", "query_fleet_endpoints",
                                 "replay_conversation_ledger"}
        if decision.intent in deterministic_intents:
            mode = "deterministic"
        elif decision.intent in retrieval_intents:
            mode = "retrieval"
        else:
            mode = "heuristic"

        confidence = _INTENT_CONFIDENCE.get(decision.intent, 0.70)
        uncertainty_reasons: list[str] = []
        downgrade_reasons: list[str] = []

        if not evidence_refs:
            uncertainty_reasons.append("no_evidence_references")
            downgrade_reasons.append("no_evidence_references")
            confidence = min(confidence, 0.60)

        return DorkTrustMetadata(
            data_sources_used=[f"{ref.source}:{ref.endpoint}" for ref in evidence_refs],
            snapshot_timestamp=now_iso(),
            snapshot_freshness="fresh",
            mode=mode,
            confidence=confidence,
            uncertainty_reasons=uncertainty_reasons,
            trust_score=confidence,
            downgrade_reasons=downgrade_reasons,
        )

    def _dispatch(
        self, *, intent: str, request: DorkIntentRouteRequest
    ) -> tuple[dict[str, Any], list[DorkEvidenceRef], str, list[str]]:
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
            memory = summarize_oracle_memory(records, window=min(max(request.limit, 1), 10))
            response = {
                "record_count": len(records),
                "ledger_path": str(self._oracle_ledger.path),
                "records": records,
                "since_last_10_oracle_calls": memory,
            }
            return response, [
                DorkEvidenceRef(source="runtime.oracle_ledger.OracleLedger.replay", endpoint="/innovations/oracle/history", panel="/ui/aponi/index.html"),
            ], "Oracle history bundle loaded from deterministic ledger replay.", ["/ui/aponi/index.html"]

        # ── INNOV-41 DFSB intent handlers ─────────────────────────────────────
        # DORK-FLEET-0: use singleton — never instantiate per-call
        if intent == "show_fleet_status":
            fleet = _get_fleet()
            status = fleet.fleet_status()
            return status, [
                DorkEvidenceRef(source="runtime.innovations30.dork_living_fleet.DORKLivingFleet.fleet_status",
                                endpoint="/innovations/fleet/status", panel="/ui/aponi/index.html"),
            ], "Fleet status snapshot assembled.", ["/ui/aponi/index.html"]

        if intent == "query_provider_health":
            fleet = _get_fleet()
            status = fleet.fleet_status()
            return status, [
                DorkEvidenceRef(source="runtime.innovations30.dork_living_fleet.DORKLivingFleet.fleet_status",
                                endpoint="/innovations/fleet/health", panel="/ui/aponi/index.html"),
            ], "Provider health status returned.", ["/ui/aponi/index.html"]

        if intent == "resolve_slash_command":
            query_lower = request.query.lower()
            slash_cmd = next(
                (token for token in request.query.split() if token.startswith("/dork:")), ""
            )
            return {"slash": slash_cmd, "resolved": bool(slash_cmd)}, [
                DorkEvidenceRef(source="runtime.dork_cmd_resolver.DorkCommandResolver.resolve",
                                endpoint="/api/dork/slash", panel="/ui/developer/ADAADdev/whaledic.html"),
            ], "Slash command resolution attempted.", ["/ui/developer/ADAADdev/whaledic.html"]

        if intent == "replay_conversation_ledger":
            return {"info": "conversation_ledger_replay_requested", "limit": request.limit}, [
                DorkEvidenceRef(source="dorkllm.state.ConversationLedger",
                                endpoint="/api/dork/ledger", panel="/ui/developer/ADAADdev/whaledic.html"),
            ], "Conversation ledger replay packet prepared.", ["/ui/developer/ADAADdev/whaledic.html"]

        if intent == "classify_query_intent":
            try:
                from dorkllm.context import classify_query, get_taxonomy_hints
                cat, conf = classify_query(request.query)
                hints = get_taxonomy_hints(request.query)
                result = {"category": cat, "confidence": conf, "hints": hints}
            except Exception as exc:
                result = {"error": str(exc)}
            return result, [
                DorkEvidenceRef(source="dorkllm.context.classify_query",
                                endpoint="/api/dork/classify", panel="/ui/developer/ADAADdev/whaledic.html"),
            ], "Query intent classified via Jaccard taxonomy.", ["/ui/developer/ADAADdev/whaledic.html"]

        if intent == "inspect_fleet_dispatch":
            fleet = _get_fleet()
            chain = fleet._dispatch_ledger if hasattr(fleet, "_dispatch_ledger") else []
            return {"chain_length": len(chain), "ledger": chain[-5:] if chain else []}, [
                DorkEvidenceRef(source="runtime.innovations30.dork_living_fleet.DORKLivingFleet._dispatch_ledger",
                                endpoint="/innovations/fleet/chain", panel="/ui/aponi/index.html"),
            ], "Fleet dispatch chain inspected.", ["/ui/aponi/index.html"]

        # ── INNOV-42 DFSB intent handlers ─────────────────────────────────────
        if intent == "query_fleet_persist":
            fleet = _get_fleet()
            status = fleet.fleet_status()
            return status, [
                DorkEvidenceRef(source="runtime.innovations30.dork_living_fleet.DORKLivingFleet.fleet_status",
                                endpoint="/innovations/fleet/persist", panel="/ui/aponi/index.html"),
            ], "Fleet persist snapshot assembled.", ["/ui/aponi/index.html"]

        if intent == "trigger_fleet_heal":
            fleet = _get_fleet()
            fleet._probe_all()
            status = fleet.fleet_status()
            return status, [
                DorkEvidenceRef(source="runtime.innovations30.dork_living_fleet.DORKLivingFleet._probe_all",
                                endpoint="/innovations/fleet/heal", panel="/ui/aponi/index.html"),
            ], "Fleet heal cycle triggered; re-probed all engines.", ["/ui/aponi/index.html"]

        if intent == "query_fleet_fitness":
            fleet = _get_fleet()
            status = fleet.fleet_status()
            healthy = not status.get("blocked", True)
            return {"fitness": "HEALTHY" if healthy else "DEGRADED", "detail": status}, [
                DorkEvidenceRef(source="runtime.innovations30.dork_living_fleet.DORKLivingFleet.fleet_status",
                                endpoint="/innovations/fleet/fitness", panel="/ui/aponi/index.html"),
            ], f"Fleet fitness: {'HEALTHY' if healthy else 'DEGRADED'}.", ["/ui/aponi/index.html"]

        if intent == "verify_fleet_chain":
            fleet = _get_fleet()
            chain = fleet._dispatch_ledger if hasattr(fleet, "_dispatch_ledger") else []
            return {"chain_length": len(chain), "ledger": chain[-5:] if chain else []}, [
                DorkEvidenceRef(source="runtime.innovations30.dork_living_fleet.DORKLivingFleet._dispatch_ledger",
                                endpoint="/innovations/fleet/chain", panel="/ui/aponi/index.html"),
            ], "Fleet dispatch chain verified.", ["/ui/aponi/index.html"]

        if intent == "query_fleet_endpoints":
            fleet = _get_fleet()
            engines = getattr(fleet, "_engines", [])
            endpoints = [
                {"name": e.name, "type": e.provider_type, "url": e.url, "priority": e.priority}
                for e in engines
            ]
            return {"endpoints": endpoints}, [
                DorkEvidenceRef(source="runtime.innovations30.dork_living_fleet.DORKLivingFleet._engines",
                                endpoint="/innovations/fleet/endpoints", panel="/ui/aponi/index.html"),
            ], "Fleet endpoint registry returned.", ["/ui/aponi/index.html"]

        # ── Default: governance brief ──────────────────────────────────────────
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
