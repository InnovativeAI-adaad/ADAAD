# SPDX-License-Identifier: Apache-2.0
"""Phase 22 — Proposal Hardening

PR-22-01  fallback_to_noop=False as the LLMProviderConfig default
PR-22-02  MarketFitnessIntegrator default-on in EvolutionLoop

Tests:
  PR-22-01-A  LLMProviderConfig() default fallback_to_noop is False
  PR-22-01-B  load_provider_config({}) default fallback_to_noop is False
  PR-22-01-C  ADAAD_LLM_FALLBACK_TO_NOOP=true opts back in
  PR-22-01-D  _safe_failure with fallback_to_noop=False returns empty payload (no noop)
  PR-22-01-E  _safe_failure with fallback_to_noop=True still returns noop payload
  PR-22-02-A  EvolutionLoop() default-constructs MarketFitnessIntegrator
  PR-22-02-B  EvolutionLoop(market_integrator=explicit) respects explicit injection
  PR-22-02-C  EvolutionLoop._market_integrator is not None without injection
  PR-22-02-D  run_epoch() populates live_market_score / market_confidence from integrator
  PR-22-02-E  auto-provisioned integrator is MarketFitnessIntegrator instance
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from runtime.intelligence.llm_provider import (
    LLMProviderConfig,
    LLMProviderClient,
    load_provider_config,
)
from runtime.evolution.evolution_loop import EvolutionLoop, EpochResult
from runtime.market.market_fitness_integrator import MarketFitnessIntegrator, IntegrationResult
from runtime.autonomy.ai_mutation_proposer import CodebaseContext


pytestmark = pytest.mark.autonomous_critical

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context(epoch_id: str = "epoch-ph22") -> CodebaseContext:
    return CodebaseContext(
        file_summaries={},
        recent_failures=[],
        current_epoch_id=epoch_id,
        explore_ratio=0.5,
    )


def _make_loop(**kwargs) -> EvolutionLoop:
    return EvolutionLoop(api_key="test-key", simulate_outcomes=True, **kwargs)


# ---------------------------------------------------------------------------
# PR-22-01-A — LLMProviderConfig default fallback_to_noop is False
# ---------------------------------------------------------------------------

def test_pr22_01_a_config_default_fallback_is_false():
    cfg = LLMProviderConfig(provider="anthropic", api_key="k", model="m", timeout_seconds=5, max_tokens=100)
    assert cfg.fallback_to_noop is False


# ---------------------------------------------------------------------------
# PR-22-01-B — load_provider_config({}) default is False
# ---------------------------------------------------------------------------

def test_pr22_01_b_load_config_default_fallback_is_false():
    cfg = load_provider_config({})
    assert cfg.fallback_to_noop is False


# ---------------------------------------------------------------------------
# PR-22-01-C — ADAAD_LLM_FALLBACK_TO_NOOP=true opts back in
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("val", ["true", "True", "1", "yes", "on"])
def test_pr22_01_c_env_var_opts_back_in(val):
    cfg = load_provider_config({"ADAAD_LLM_FALLBACK_TO_NOOP": val,
                                 "ADAAD_ANTHROPIC_API_KEY": "k"})
    assert cfg.fallback_to_noop is True


# ---------------------------------------------------------------------------
# PR-22-01-D — _safe_failure with fallback_to_noop=False returns no noop
# ---------------------------------------------------------------------------

def test_pr22_01_d_safe_failure_no_fallback_returns_empty():
    cfg = LLMProviderConfig(
        provider="anthropic", api_key="k", model="m", timeout_seconds=5, max_tokens=100,
        fallback_to_noop=False,
    )
    client = LLMProviderClient(cfg)
    result = client._safe_failure("test_code", "test message")
    assert result.ok is False
    assert result.fallback_used is False
    assert result.payload == {}


# ---------------------------------------------------------------------------
# PR-22-01-E — _safe_failure with fallback_to_noop=True still returns noop
# ---------------------------------------------------------------------------

def test_pr22_01_e_safe_failure_with_fallback_returns_noop():
    cfg = LLMProviderConfig(
        provider="anthropic", api_key="k", model="m", timeout_seconds=5, max_tokens=100,
        fallback_to_noop=True,
    )
    client = LLMProviderClient(cfg)
    result = client._safe_failure("test_code", "test message")
    assert result.ok is False
    assert result.fallback_used is True
    assert isinstance(result.payload, dict)
    assert result.payload  # non-empty noop payload


# ---------------------------------------------------------------------------
# PR-22-02-A — EvolutionLoop() default-constructs MarketFitnessIntegrator
# ---------------------------------------------------------------------------

def test_pr22_02_a_default_constructs_market_integrator():
    loop = _make_loop()
    assert loop._market_integrator is not None


# ---------------------------------------------------------------------------
# PR-22-02-B — explicit injection is respected
# ---------------------------------------------------------------------------

def test_pr22_02_b_explicit_injection_respected():
    explicit = MarketFitnessIntegrator()
    loop = _make_loop(market_integrator=explicit)
    assert loop._market_integrator is explicit


# ---------------------------------------------------------------------------
# PR-22-02-C — _market_integrator is not None without injection
# ---------------------------------------------------------------------------

def test_pr22_02_c_market_integrator_never_none_by_default():
    loop = EvolutionLoop(api_key="x")
    assert loop._market_integrator is not None


# ---------------------------------------------------------------------------
# PR-22-02-D — run_epoch() populates market fields from auto integrator
# ---------------------------------------------------------------------------

def test_pr22_02_d_run_epoch_populates_market_fields(monkeypatch):
    stub = MagicMock(spec=MarketFitnessIntegrator)
    stub.consecutive_synthetic_epochs = 0
    stub.integrate.return_value = IntegrationResult(
        epoch_id="epoch-ph22",
        live_market_score=0.77,
        confidence=0.90,
        is_synthetic=False,
        adapter_id="stub",
        lineage_digest="abc123",
        signal_source="stub_feed",
        consecutive_synthetic_epochs=0,
    )

    loop = _make_loop(market_integrator=stub)
    with patch("runtime.evolution.evolution_loop.propose_from_all_agents",
               return_value={"architect": []}):
        result = loop.run_epoch(_make_context())

    assert result.live_market_score == pytest.approx(0.77)
    assert result.market_confidence == pytest.approx(0.90)
    assert result.market_is_synthetic is False


# ---------------------------------------------------------------------------
# PR-22-02-E — auto-provisioned integrator is MarketFitnessIntegrator
# ---------------------------------------------------------------------------

def test_pr22_02_e_auto_provisioned_type():
    loop = _make_loop()
    assert isinstance(loop._market_integrator, MarketFitnessIntegrator)
