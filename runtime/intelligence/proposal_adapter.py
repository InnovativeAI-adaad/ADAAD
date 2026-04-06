# SPDX-License-Identifier: Apache-2.0
"""Adapter that bridges Proposal contracts to concrete LLM provider calls.

Phase 16: Strategy-aware prompt routing. Each of the six STRATEGY_TAXONOMY
strategies now receives a tailored system prompt that focuses the LLM on the
correct mutation target. strategy_id is validated against STRATEGY_TAXONOMY
before any prompt construction — injection of unknown IDs raises ValueError.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from runtime.intelligence.llm_provider import LLMProviderClient
from runtime.intelligence.proposal import ProposalModule, ProposalTargetFile
from runtime.intelligence.strategy import STRATEGY_TAXONOMY, StrategyDecision, StrategyInput

# ---------------------------------------------------------------------------
# Per-strategy system prompt templates — Phase 16
# ---------------------------------------------------------------------------

_STRATEGY_SYSTEM_PROMPTS: dict[str, str] = {
    "adaptive_self_mutate": (
        "You are an AGM proposal engine targeting immediate mutation gain. "
        "Propose concrete code changes that increase mutation score and acceptance rate. "
        "Return strict JSON with fields: title, summary, estimated_impact, real_diff, "
        "target_files, projected_impact, metadata."
    ),
    "conservative_hold": (
        "You are an AGM proposal engine in conservative mode. "
        "Propose minimal, low-risk changes that preserve lineage health and governance stability. "
        "Avoid large diffs. Prefer documentation, configuration, or test-only changes. "
        "Return strict JSON with fields: title, summary, estimated_impact, real_diff, "
        "target_files, projected_impact, metadata."
    ),
    "structural_refactor": (
        "You are an AGM proposal engine targeting structural refactoring. "
        "Lineage health is degraded — propose changes that reduce coupling, eliminate "
        "technical debt, and restore clean architectural boundaries. "
        "Return strict JSON with fields: title, summary, estimated_impact, real_diff, "
        "target_files, projected_impact, metadata."
    ),
    "test_coverage_expansion": (
        "You are an AGM proposal engine targeting test coverage expansion. "
        "Governance debt is elevated — propose new tests, fixture improvements, or "
        "coverage-gap closures that reduce governance debt accumulation. "
        "Return strict JSON with fields: title, summary, estimated_impact, real_diff, "
        "target_files, projected_impact, metadata."
    ),
    "performance_optimization": (
        "You are an AGM proposal engine targeting performance optimisation. "
        "Market fitness pressure is active — propose changes that reduce latency, "
        "memory footprint, or compute cost without sacrificing governance invariants. "
        "Return strict JSON with fields: title, summary, estimated_impact, real_diff, "
        "target_files, projected_impact, metadata."
    ),
    "safety_hardening": (
        "You are an AGM proposal engine in safety hardening mode. "
        "Governance debt is critical — propose changes that close security surface, "
        "harden validation, tighten invariant enforcement, and reduce risk exposure. "
        "Do NOT propose changes that weaken any existing constitutional rule. "
        "Return strict JSON with fields: title, summary, estimated_impact, real_diff, "
        "target_files, projected_impact, metadata."
    ),
}

# Fallback for any taxonomy member missing from the dict (defensive).
_DEFAULT_SYSTEM_PROMPT = (
    "You are an AGM proposal engine. Return strict JSON with fields: "
    "title, summary, estimated_impact, real_diff, target_files, projected_impact, metadata."
)


def _system_prompt_for_strategy(strategy_id: str) -> str:
    """Return the strategy-specific system prompt.

    Validates strategy_id against STRATEGY_TAXONOMY before lookup.
    Raises ValueError on unknown strategy_id.
    """
    if strategy_id not in STRATEGY_TAXONOMY:
        raise ValueError(
            f"strategy_id '{strategy_id}' not in STRATEGY_TAXONOMY — "
            f"prompt injection blocked. Valid IDs: {sorted(STRATEGY_TAXONOMY)}"
        )
    return _STRATEGY_SYSTEM_PROMPTS.get(strategy_id, _DEFAULT_SYSTEM_PROMPT)


# ---------------------------------------------------------------------------
# ProposalAdapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProposalAdapter:
    """LLM-backed proposal adapter with replay/evidence-friendly payload capture.

    Phase 16: system prompt is now routed per strategy_id from STRATEGY_TAXONOMY.
    Unknown strategy_ids are blocked before any LLM call — fail-closed on injection.

    Phase 89 — REPLAY-CAPTURE-0:
    Every LLM call writes a ProposalCaptureEvent to *capture_ledger* BEFORE
    the response is passed to downstream scoring.  Pass a ProposalCaptureLedger
    instance to enable; if None, a module-level default ledger is used so the
    invariant is always satisfied.
    """

    provider_client:  LLMProviderClient
    proposal_module:  ProposalModule
    capture_ledger:   object | None = None   # ProposalCaptureLedger | None
    _call_counter:    object = None          # internal — not part of public API

    def build_from_strategy(
        self,
        *,
        context: StrategyInput,
        strategy: StrategyDecision,
        epoch_id: str = "unknown",
        call_index: int = 0,
    ):
        system_prompt = _system_prompt_for_strategy(strategy.strategy_id)
        user_prompt = (
            f"cycle_id={context.cycle_id}\n"
            f"strategy_id={strategy.strategy_id}\n"
            f"rationale={strategy.rationale}\n"
            f"signals={json.dumps(context.signals, sort_keys=True)}"
        )

        provider_result = self.provider_client.request_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        # ── REPLAY-CAPTURE-0 ─────────────────────────────────────────────
        # Write capture event BEFORE using the response in any downstream
        # step.  This is the constitutional enforcement point.
        try:
            from runtime.evolution.proposal_capture import (
                ProposalCaptureEvent,
                get_default_ledger,
            )
            ledger = self.capture_ledger or get_default_ledger()
            response_text = json.dumps(
                provider_result.payload, sort_keys=True
            ) if provider_result.payload else ""
            capture_event = ProposalCaptureEvent.build(
                epoch_id=epoch_id,
                cycle_id=context.cycle_id,
                call_index=call_index,
                strategy_id=strategy.strategy_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_text=response_text,
                provider_ok=provider_result.ok,
                error_code=getattr(provider_result, "error_code", None),
            )
            ledger.append(capture_event)
        except Exception as _cap_exc:  # pragma: no cover
            import logging as _log
            _log.getLogger(__name__).error(
                "REPLAY-CAPTURE-0 VIOLATION: capture ledger write failed: %s — "
                "proposal is constitutionally invalid but continuing fail-open "
                "to preserve liveness; incident must be reviewed.",
                _cap_exc,
            )
        # ── end REPLAY-CAPTURE-0 ─────────────────────────────────────────

        payload = provider_result.payload if isinstance(provider_result.payload, dict) else {}
        governance_decision = (
            {"decision": "escalate/reject", "reason": provider_result.error_code}
            if (not provider_result.ok and provider_result.error_code == "governance_reject_deterministic_unsupported")
            else {}
        )

        return self.proposal_module.build(
            cycle_id=context.cycle_id,
            strategy_id=strategy.strategy_id,
            rationale=self._read_string(payload, "summary") or strategy.rationale,
            real_diff=self._read_string(payload, "real_diff") or "",
            target_files=self._parse_target_files(payload.get("target_files")),
            projected_impact=self._read_mapping(payload, "projected_impact"),
            evidence={
                "llm_provider_result": provider_result.to_dict(),
                "llm_raw_payload": payload,
                "strategy_prompt_version": "16.0",
                "evidence_schema_version": "dork-evidence-v1",
                "source_path": "provider_adapter",
            },
            metadata={
                "cycle_id": context.cycle_id,
                "strategy_id": strategy.strategy_id,
                **governance_decision,
                **self._read_mapping(payload, "metadata"),
            },
        )

    @staticmethod
    def _read_string(payload: Mapping[str, Any], key: str) -> str | None:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
        return None

    @staticmethod
    def _read_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return dict(value)
        return {}

    @staticmethod
    def _parse_target_files(value: Any) -> tuple[ProposalTargetFile, ...]:
        if not isinstance(value, list):
            return ()

        parsed: list[ProposalTargetFile] = []
        for item in value:
            if not isinstance(item, Mapping):
                continue
            path = item.get("path", "")
            if isinstance(path, str) and path.strip():
                parsed.append(
                    ProposalTargetFile(
                        path=path,
                        language=str(item.get("language")) if isinstance(item.get("language"), str) else None,
                        exists=bool(item.get("exists")) if "exists" in item else None,
                        content=str(item.get("content")) if isinstance(item.get("content"), str) else None,
                        metadata=dict(item.get("metadata")) if isinstance(item.get("metadata"), Mapping) else {},
                    )
                )
        return tuple(parsed)
