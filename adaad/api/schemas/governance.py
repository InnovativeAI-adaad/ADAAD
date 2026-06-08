# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, validator


class GovernanceStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ParallelGateAxisSpec(GovernanceStrictModel):
    axis: StrictStr = Field(min_length=1, max_length=64)
    rule_id: StrictStr = Field(min_length=1, max_length=128)
    ok: StrictBool | None = None
    reason: StrictStr | None = Field(default=None, min_length=1, max_length=256)


class ParallelGateEvaluateRequest(GovernanceStrictModel):
    mutation_id: StrictStr = Field(min_length=1, max_length=128)
    trust_mode: StrictStr = Field(default="standard", min_length=1, max_length=32)
    axis_specs: list[ParallelGateAxisSpec] = Field(...)

    @validator("axis_specs")
    @classmethod
    def _axis_specs_len(cls, v):
        if not 1 <= len(v) <= 20:
            raise ValueError("axis_specs must have 1–20 entries")
        return v
    human_override: StrictBool = False


class ParallelGateAxisResult(GovernanceStrictModel):
    axis: StrictStr
    rule_id: StrictStr
    ok: StrictBool
    reason: StrictStr
    duration_ms: float


class ParallelGateFailedRule(GovernanceStrictModel):
    axis: StrictStr
    rule_id: StrictStr


class ParallelGateDecision(GovernanceStrictModel):
    approved: StrictBool
    decision: Literal["approve", "reject"]
    mutation_id: StrictStr
    trust_mode: StrictStr
    reason_codes: list[StrictStr] = Field(default_factory=list)
    failed_rules: list[ParallelGateFailedRule] = Field(default_factory=list)
    axis_results: list[ParallelGateAxisResult] = Field(default_factory=list)
    decision_id: StrictStr
    human_override: StrictBool
    gate_version: StrictStr


class ParallelGateEvaluateResponse(GovernanceStrictModel):
    ok: StrictBool
    decision: ParallelGateDecision
    wall_elapsed_ms: float
    gate_version: StrictStr
    max_workers: StrictInt
    axis_count: StrictInt


class ParallelGateProbeDefinition(GovernanceStrictModel):
    rule_id: StrictStr
    default_ok: StrictBool
    default_reason: StrictStr


class ParallelGateProbeLibraryResponse(GovernanceStrictModel):
    ok: StrictBool
    axes: dict[StrictStr, list[ParallelGateProbeDefinition]]
    total_probes: StrictInt
    gate_version: StrictStr


class FastPathRoutePreviewRequest(GovernanceStrictModel):
    mutation_id: StrictStr = Field(default="unknown", min_length=1, max_length=128)
    intent: StrictStr = Field(default="", max_length=256)
    files_touched: list[StrictStr] = Field(default_factory=list)
    loc_added: StrictInt = 0
    loc_deleted: StrictInt = 0
    risk_tags: list[StrictStr] = Field(default_factory=list)


class FastPathRoutePreviewSummary(GovernanceStrictModel):
    tier: StrictStr
    skip_heavy_scoring: StrictBool
    require_human_review: StrictBool


class FastPathRoutePreviewDecision(GovernanceStrictModel):
    mutation_id: StrictStr
    tier: StrictStr
    reasons: list[StrictStr]
    decision_digest: StrictStr
    route_version: StrictStr


class FastPathRoutePreviewResponse(GovernanceStrictModel):
    ok: StrictBool
    summary: FastPathRoutePreviewSummary
    decision: FastPathRoutePreviewDecision


class FastPathEntropyGateRequest(GovernanceStrictModel):
    mutation_id: StrictStr = Field(default="unknown", min_length=1, max_length=128)
    estimated_bits: StrictInt = 0
    sources: list[StrictStr] = Field(default_factory=list)
    strict: StrictBool = True


class FastPathEntropyResult(GovernanceStrictModel):
    verdict: Literal["ALLOW", "WARN", "DENY"]
    reason: StrictStr
    gate_digest: StrictStr
    gate_version: StrictStr
    estimated_bits: StrictInt
    budget_bits: StrictInt


class FastPathEntropyGateResponse(GovernanceStrictModel):
    ok: StrictBool
    denied: StrictBool
    result: FastPathEntropyResult


class FastPathStatsVersions(GovernanceStrictModel):
    route_optimizer: StrictStr
    entropy_gate: StrictStr
    fast_path_scorer: StrictStr
    checkpoint_chain: StrictStr


class FastPathStatsEntropyThresholds(GovernanceStrictModel):
    warn_bits: StrictInt
    deny_bits: StrictInt
    budget_bits: StrictInt


class FastPathStatsRouteConfig(GovernanceStrictModel):
    tiers: dict[StrictStr, StrictStr]
    elevated_path_prefixes: list[StrictStr]
    elevated_intent_keywords: list[StrictStr]
    trivial_op_types: list[StrictStr]


class FastPathStatsResponse(GovernanceStrictModel):
    ok: StrictBool
    versions: FastPathStatsVersions
    entropy_thresholds: FastPathStatsEntropyThresholds
    route_config: FastPathStatsRouteConfig


class FastPathCheckpointLink(GovernanceStrictModel):
    epoch_id: StrictStr
    chain_digest: StrictStr
    predecessor_digest: StrictStr
    chain_version: StrictStr


class FastPathCheckpointVerifyResponse(GovernanceStrictModel):
    ok: StrictBool
    chain_version: StrictStr
    genesis_digest: StrictStr
    head_digest: StrictStr
    chain_length: StrictInt
    integrity: StrictBool
    links: list[FastPathCheckpointLink]


class SemVerVerdictRecord(GovernanceStrictModel):
    mutation_id: StrictStr
    declared_impact: StrictStr
    detected_impact: StrictStr
    contract_honored: StrictBool
    violations: list[StrictStr]
    verdict_digest: StrictStr
    timestamp: float


class SemVerAnalysisResponse(GovernanceStrictModel):
    detected_impact: StrictStr
    breaking_signals: list[StrictStr]
    feature_signals: list[StrictStr]
    public_api_removals: StrictInt
    public_api_additions: StrictInt


class GovernanceSemVerStatusResponse(GovernanceStrictModel):
    ok: StrictBool
    innovation: StrictInt
    innovation_name: StrictStr
    mutation_id: StrictStr
    contract_status: Literal["PASS", "FAIL", "UNKNOWN"]
    verdict: SemVerVerdictRecord | None = None
    history_count: StrictInt
    audit_history: list[SemVerVerdictRecord]
    analysis: SemVerAnalysisResponse