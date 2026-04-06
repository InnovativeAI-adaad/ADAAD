import pytest
pytestmark = pytest.mark.regression_standard

from runtime.intelligence.llm_provider import LLMProviderClient, LLMProviderConfig


def _cfg(*, provider: str, deterministic_mode: bool = True) -> LLMProviderConfig:
    return LLMProviderConfig(
        provider=provider,
        api_key="local-key",
        model="llama3.1",
        timeout_seconds=5.0,
        max_tokens=128,
        base_url="http://localhost:11434/v1",
        deterministic_mode=deterministic_mode,
        deterministic_opts={"seed": 17, "temperature": 0.0},
    )


def test_lineage_dork_replay_deterministic_response_and_evidence_digest(monkeypatch):
    client = LLMProviderClient(_cfg(provider="ollama", deterministic_mode=True))

    def _fake_dispatch(system: str, user: str) -> str:
        assert system
        assert user
        return '{"proposal_type":"noop","reason":"deterministic-test","actions":[]}'

    monkeypatch.setattr(client, "_dispatch_request", _fake_dispatch)

    first = client.request_json(system_prompt="sys", user_prompt="usr")
    second = client.request_json(system_prompt="sys", user_prompt="usr")

    assert first.ok is True
    assert second.ok is True
    assert first.response_sha256 == second.response_sha256
    assert first.evidence_digest == second.evidence_digest


def test_lineage_dork_rejects_when_deterministic_mode_unsupported():
    client = LLMProviderClient(_cfg(provider="openai", deterministic_mode=True))

    result = client.request_json(system_prompt="sys", user_prompt="usr")

    assert result.ok is False
    assert result.error_code == "governance_reject_deterministic_unsupported"
    assert result.payload.get("governance", {}).get("action") == "escalate/reject"
