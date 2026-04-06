# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import pytest
pytestmark = pytest.mark.regression_standard

from runtime.intelligence.llm_provider import (
    EvolutionContextContract,
    LLMProviderClient,
    LLMProviderConfig,
    ResourceProbeSnapshot,
    build_evolution_user_prompt,
    load_provider_config,
)


class _FakeClient:
    def __init__(self, response_text: str | None = None, error: Exception | None = None) -> None:
        self._response_text = response_text
        self._error = error
        self.messages = self

    def create(self, **_: object):
        if self._error is not None:
            raise self._error

        class _Block:
            def __init__(self, text: str) -> None:
                self.text = text

        class _Response:
            def __init__(self, text: str) -> None:
                self.content = [_Block(text)]

        return _Response(self._response_text or "{}")


class _ClientWithStubBuild(LLMProviderClient):
    def __init__(self, *args, stub_client=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._stub_client = stub_client

    def _dispatch_request(self, system: str, user: str, *, model: str) -> str:  # noqa: ARG002
        return self._stub_client.create().content[0].text


def test_config_defaults_and_overrides() -> None:
    cfg = load_provider_config(
        {
            "ADAAD_ANTHROPIC_API_KEY": "key",
            "ADAAD_LLM_MODEL": "claude-test",
            "ADAAD_LLM_TIMEOUT_SECONDS": "9",
            "ADAAD_LLM_MAX_TOKENS": "123",
            "ADAAD_LLM_FALLBACK_TO_NOOP": "false",
        }
    )

    assert cfg.api_key == "key"
    assert cfg.model == "claude-test"
    assert cfg.timeout_seconds == 9
    assert cfg.max_tokens == 123
    assert cfg.fallback_to_noop is False


def test_missing_api_key_returns_safe_noop() -> None:
    client = LLMProviderClient(LLMProviderConfig(provider="openai", api_key="", model="m", timeout_seconds=2, max_tokens=200, fallback_to_noop=True))

    result = client.request_json(system_prompt="s", user_prompt="u")

    assert result.ok is False
    assert result.error_code == "missing_api_key"
    assert result.fallback_used is True
    assert result.payload["proposal_type"] == "noop"


def test_invalid_json_returns_safe_error() -> None:
    client = _ClientWithStubBuild(
        LLMProviderConfig(provider="openai", api_key="k", model="m", timeout_seconds=2, max_tokens=200, fallback_to_noop=True),
        stub_client=_FakeClient(response_text="not-json"),
    )

    result = client.request_json(system_prompt="s", user_prompt="u")

    assert result.ok is False
    assert result.error_code == "provider_request_failed"
    assert result.fallback_used is True
    assert result.payload["proposal_type"] == "noop"


def test_valid_json_response_success() -> None:
    client = _ClientWithStubBuild(
        LLMProviderConfig(provider="openai", api_key="k", model="m", timeout_seconds=2, max_tokens=200, fallback_to_noop=True),
        stub_client=_FakeClient(
            response_text=(
                '{"proposal_type":"patch","actions":[],"proposal_hypothesis":"Reduce latency",'
                '"expected_roi":0.2,"risk_confidence":0.7,"fallback_plan":"Revert patch"}'
            )
        ),
    )

    result = client.request_json(system_prompt="s", user_prompt="u")

    assert result.ok is True
    assert result.payload["proposal_type"] == "patch"


@pytest.fixture
def evolution_context() -> EvolutionContextContract:
    return EvolutionContextContract(
        prior_cycle_summaries=["Cycle 7 improved retries", "Cycle 8 reduced token cost"],
        top_strategy_lineage=["parent:v1", "child:v2"],
        rejection_causes=["schema_mismatch", "unsafe_patch"],
        accepted_mutations=[
            {"mutation_id": "m1", "summary": "Cache warmup"},
            {"mutation_id": "m2", "summary": "Retry jitter", "secret": "never-send"},
        ],
        rejected_mutations=[
            {"mutation_id": "m3", "summary": "Aggressive timeout", "api_key": "abc123"},
            {"mutation_id": "m4", "summary": "Unbounded loop", "reason": "high risk"},
        ],
        federated_insight_summaries=["Node A saw ROI +0.1", "Node B saw rollback risk"],
    )


def test_build_evolution_user_prompt_uses_compact_window_and_redaction(evolution_context: EvolutionContextContract) -> None:
    prompt = build_evolution_user_prompt(evolution_context, history_window=1, federated_window=1)

    assert "m1" not in prompt
    assert "m2" in prompt
    assert "m4" in prompt
    assert "Node A" not in prompt
    assert "Node B" in prompt
    assert "abc123" not in prompt
    assert "[redacted]" in prompt


def test_malformed_adaptive_response_downgrades_to_noop() -> None:
    client = _ClientWithStubBuild(
        LLMProviderConfig(provider="openai", api_key="k", model="m", timeout_seconds=2, max_tokens=200, fallback_to_noop=True),
        stub_client=_FakeClient(response_text='{"proposal_type":"patch","actions":[]}'),
    )

    result = client.request_json(system_prompt="s", user_prompt="u")

    assert result.ok is False
    assert result.error_code == "provider_request_failed"
    assert result.fallback_used is True
    assert result.payload["proposal_type"] == "noop"


def test_malformed_adaptive_response_without_fallback_returns_error_payload() -> None:
    client = _ClientWithStubBuild(
        LLMProviderConfig(provider="openai", api_key="k", model="m", timeout_seconds=2, max_tokens=200, fallback_to_noop=False),
        stub_client=_FakeClient(response_text='{"proposal_type":"patch","actions":[]}'),
    )

    result = client.request_json(system_prompt="s", user_prompt="u")

    assert result.ok is False
    assert result.error_code == "provider_request_failed"
    assert result.fallback_used is False
    assert result.payload == {}


def test_resource_constrained_chain_selects_lower_quantized_model() -> None:
    class _StableModelClient(LLMProviderClient):
        def _dispatch_request(self, system: str, user: str, *, model: str) -> str:  # noqa: ARG002
            return '{"proposal_type":"noop","reason":"ok","actions":[]}'

    cfg = LLMProviderConfig(
        provider="openai",
        api_key="k",
        model="acme-model-q16",
        fallback_models=("acme-model-q8", "acme-model-q4"),
        timeout_seconds=2,
        max_tokens=200,
        fallback_to_noop=True,
    )
    client = _StableModelClient(
        cfg,
        probe_fn=lambda: ResourceProbeSnapshot(ram_available_mb=4000, vram_available_mb=3200, cpu_available_percent=65),
    )

    result = client.request_json(system_prompt="s", user_prompt="u")

    assert result.ok is True
    assert (result.metadata or {}).get("selected_model") == "acme-model-q8"
    rejected = (result.metadata or {}).get("rejected_candidates") or []
    assert rejected[0]["model"] == "acme-model-q16"


def test_fallback_chain_failure_is_stable_and_trace_identical() -> None:
    class _NeverCalledClient(LLMProviderClient):
        def _dispatch_request(self, system: str, user: str, *, model: str) -> str:  # noqa: ARG002
            raise AssertionError("dispatch should not be reached when selection fails")

    cfg = LLMProviderConfig(
        provider="openai",
        api_key="k",
        model="acme-model-q16",
        fallback_models=("acme-model-q8", "acme-model-q4"),
        timeout_seconds=2,
        max_tokens=200,
        fallback_to_noop=True,
        host_id="edge-a",
        host_capability_profiles={"edge-a": {"allowed_models": ["acme-model-q8", "acme-model-q4"]}},
    )
    probe = lambda: ResourceProbeSnapshot(ram_available_mb=300, vram_available_mb=0, cpu_available_percent=5)  # noqa: E731
    client = _NeverCalledClient(cfg, probe_fn=probe)

    first = client.request_json(system_prompt="s", user_prompt="u")
    second = client.request_json(system_prompt="s", user_prompt="u")

    assert first.ok is False
    assert first.error_code == "model_selection_failed"
    assert first.fallback_used is True
    assert first.metadata == second.metadata
