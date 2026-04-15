# SPDX-License-Identifier: Apache-2.0
# Phase 137 · INNOV-44 · DORK Intelligence Hardening & Capability Expansion

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, StrictBool, StrictStr

# ── DORK-INTENT-0 ─────────────────────────────────────────────────────────────
# Hard invariant: DorkIntentName MUST enumerate every intent registered in
# DorkIntentRouter._ORDERED_RULES. Any intent reachable by the router that is
# absent from this Literal type will cause Pydantic validation to reject the
# DorkIntentBundle, making the intent effectively dead code at the schema layer.
# New intents MUST be added here before being added to _ORDERED_RULES.
# ─────────────────────────────────────────────────────────────────────────────

DorkIntentName = Literal[
    # Core governance intents
    "show_gate_status",
    "explain_blockers",
    "prepare_mutation_review",
    "open_oracle_history",
    "generate_governance_brief",
    "interpret_epoch_delta",
    # INNOV-41 · Phase 132 — Living Fleet intents
    "show_fleet_status",
    "resolve_slash_command",
    "query_provider_health",
    "replay_conversation_ledger",
    "classify_query_intent",
    "inspect_fleet_dispatch",
    # INNOV-42 · Phase 133 — DFSB intents
    "query_fleet_persist",
    "trigger_fleet_heal",
    "query_fleet_fitness",
    "verify_fleet_chain",
    "query_fleet_endpoints",
]


class DorkIntentRouteRequest(BaseModel):
    """Validated request envelope for Dork query-to-intent routing."""

    query: StrictStr = Field(min_length=1, max_length=512)
    limit: int = Field(default=25, ge=1, le=200)
    epoch_id: StrictStr = Field(default="")
    before_snapshot: dict[str, Any] = Field(default_factory=dict)
    after_snapshot: dict[str, Any] = Field(default_factory=dict)


class DorkExecutionMarker(BaseModel):
    """Execution intent marker for advisory/actionable framing."""

    advisory_only: StrictBool
    actionable_next_step: StrictBool


class DorkIntentDecision(BaseModel):
    """Typed intent decision produced by deterministic query routing."""

    intent: DorkIntentName
    rationale: StrictStr
    marker: DorkExecutionMarker
    normalized_query: StrictStr


class DorkEvidenceRef(BaseModel):
    """Stable evidence reference emitted in response bundles."""

    source: StrictStr
    endpoint: StrictStr
    panel: StrictStr = Field(default="")


class DorkTrustMetadata(BaseModel):
    """Trust metadata attached to each Dork response bundle."""

    data_sources_used: list[StrictStr] = Field(default_factory=list)
    snapshot_timestamp: datetime
    snapshot_freshness: Literal["fresh", "stale", "unknown"] = "unknown"
    mode: Literal["deterministic", "retrieval", "heuristic", "consensus"] = "deterministic"
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty_reasons: list[StrictStr] = Field(default_factory=list)
    trust_score: float = Field(ge=0.0, le=1.0)
    downgrade_reasons: list[StrictStr] = Field(default_factory=list)


class DorkIntentBundle(BaseModel):
    """Deterministic response envelope returned to clients."""

    intent: DorkIntentName
    marker: DorkExecutionMarker
    summary: StrictStr
    response: dict[str, Any]
    evidence_refs: list[DorkEvidenceRef]
    aponi_panels: list[StrictStr]
    bundle_digest: StrictStr
    trust_metadata: DorkTrustMetadata


class DorkConsoleRouteRequest(BaseModel):
    """Contract payload for the UI Dork console endpoint."""

    query: StrictStr = Field(min_length=1, max_length=512)
    limit: int = Field(default=25, ge=1, le=200)
    epoch_id: StrictStr = Field(default="")
    before_snapshot: dict[str, Any] = Field(default_factory=dict)
    after_snapshot: dict[str, Any] = Field(default_factory=dict)


class DorkConsoleRouteResponse(BaseModel):
    """UI contract response for deterministic approved/blocked surfacing."""

    outcome: Literal["approved", "blocked"]
    outcome_reason: StrictStr = Field(default="")
    console_message: StrictStr
    bundle: DorkIntentBundle


class DorkConsoleRouteError(BaseModel):
    """Typed error schema for UI contract failures."""

    error_code: Literal["governance_blocked", "validation_error", "http_error"]
    message: StrictStr
    detail: dict[str, Any] = Field(default_factory=dict)
class DorkProposalExecuteRequest(BaseModel):
    """Request envelope for DORK-governed mutation proposal execution."""

    proposal: dict[str, Any]
    trust_mode: StrictStr = Field(default="standard", min_length=1, max_length=64)
    actor: StrictStr = Field(default="dork", min_length=1, max_length=128)


class DorkProposalExecuteResponse(BaseModel):
    """Response envelope for DORK-governed mutation proposal execution."""

    ok: StrictBool
    proposal_id: StrictStr
    gate_decision_id: StrictStr
    governance_decision: StrictStr
    queued_event_type: StrictStr
    queue_hash: StrictStr
