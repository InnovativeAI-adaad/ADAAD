# SPDX-License-Identifier: Apache-2.0

import json

from app.agents.mutation_request import MutationRequest
from runtime.constitution import Tier, evaluate_mutation
from security.ledger import journal


def _write_ledger_entries(path, action: str, count: int, *, epoch_id: str) -> None:
    now_iso = "2026-01-01T00:00:00Z"
    lines = []
    for _ in range(count):
        lines.append(
            json.dumps(
                {
                    "timestamp": now_iso,
                    "agent_id": "test_subject",
                    "action": action,
                    "payload": {"epoch_id": epoch_id},
                }
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_mutation_rate_blocks_when_threshold_exceeded(monkeypatch, tmp_path) -> None:
    ledger_path = tmp_path / "lineage.jsonl"
    monkeypatch.setattr(journal, "LEDGER_FILE", ledger_path)
    _write_ledger_entries(ledger_path, "mutation_executed", count=3, epoch_id="epoch-1")
    monkeypatch.setenv("ADAAD_MAX_MUTATION_RATE", "2")
    monkeypatch.setenv("ADAAD_MUTATION_RATE_WINDOW_SEC", "3600")
    monkeypatch.setenv("CRYOVANT_DEV_MODE", "1")
    monkeypatch.setenv("ADAAD_ENV", "dev")

    request = MutationRequest(
        agent_id="test_subject",
        generation_ts="now",
        intent="test",
        ops=[],
        signature="cryovant-dev-test",
        nonce="nonce",
        epoch_id="epoch-1",
    )
    verdict = evaluate_mutation(request, Tier.PRODUCTION)

    assert verdict["passed"] is False
    assert "max_mutation_rate" in verdict["blocking_failures"]
    rate_verdict = next(item for item in verdict["verdicts"] if item["rule"] == "max_mutation_rate")
    assert rate_verdict["passed"] is False
    assert rate_verdict["details"]["details"]["resolved_from_env"] == "ADAAD_MAX_MUTATION_RATE"


def test_mutation_rate_legacy_env_is_supported_with_deterministic_precedence(monkeypatch, tmp_path) -> None:
    ledger_path = tmp_path / "lineage.jsonl"
    monkeypatch.setattr(journal, "LEDGER_FILE", ledger_path)
    _write_ledger_entries(ledger_path, "mutation_executed", count=2, epoch_id="epoch-2")
    monkeypatch.setenv("ADAAD_MAX_MUTATIONS_PER_HOUR", "1")
    monkeypatch.setenv("ADAAD_MAX_MUTATION_RATE", "3")
    monkeypatch.setenv("ADAAD_MUTATION_RATE_WINDOW_SEC", "3600")
    monkeypatch.setenv("CRYOVANT_DEV_MODE", "1")
    monkeypatch.setenv("ADAAD_ENV", "dev")

    request = MutationRequest(
        agent_id="test_subject",
        generation_ts="now",
        intent="test",
        ops=[],
        signature="cryovant-dev-test",
        nonce="nonce",
        epoch_id="epoch-2",
    )
    verdict = evaluate_mutation(request, Tier.PRODUCTION)

    assert verdict["passed"] is True
    rate_verdict = next(item for item in verdict["verdicts"] if item["rule"] == "max_mutation_rate")
    assert rate_verdict["details"]["details"]["resolved_from_env"] == "ADAAD_MAX_MUTATION_RATE"
    assert rate_verdict["details"]["details"]["scope"]["epoch_id"] == "epoch-2"
