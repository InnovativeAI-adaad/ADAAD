# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, StrictBool, StrictStr

DorkIntentName = Literal[
    "show_gate_status",
    "explain_blockers",
    "prepare_mutation_review",
    "open_oracle_history",
    "generate_governance_brief",
    "interpret_epoch_delta",
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


class DorkIntentBundle(BaseModel):
    """Deterministic response envelope returned to clients."""

    intent: DorkIntentName
    marker: DorkExecutionMarker
    summary: StrictStr
    response: dict[str, Any]
    evidence_refs: list[DorkEvidenceRef]
    aponi_panels: list[StrictStr]
    bundle_digest: StrictStr
