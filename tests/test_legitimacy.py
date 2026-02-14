# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from runtime.legitimacy import evaluate_legitimacy
from security.ledger import journal


def _use_temp_ledgers(tmp_path: Path, monkeypatch) -> None:
    ledger_root = tmp_path / "ledger"
    monkeypatch.setattr(journal, "LEDGER_ROOT", ledger_root)
    monkeypatch.setattr(journal, "LEDGER_FILE", ledger_root / "lineage.jsonl")
    monkeypatch.setattr(journal, "JOURNAL_PATH", ledger_root / "cryovant_journal.jsonl")
    monkeypatch.setattr(journal, "GENESIS_PATH", ledger_root / "cryovant_journal.genesis.jsonl")


def test_evaluate_legitimacy_passes_and_persists_summary(tmp_path: Path, monkeypatch) -> None:
    _use_temp_ledgers(tmp_path, monkeypatch)
    record = {
        "record_id": "rec-001",
        "lineage": {"lineage_id": "lin-1", "parent_hash": "sha256:abc"},
        "signature": {"valid": True},
        "founders_law": {"satisfied": True},
        "capability": {"compliant": True},
        "trust_mode": {"compliant": True},
        "epoch": {"aligned": True},
        "evidence_hashes": ["sha256:e1", "sha256:e2"],
    }

    result = evaluate_legitimacy(record)

    assert result.legitimate is True
    assert result.failed_dimensions == []
    assert result.total_score == 1.0

    entries = journal.read_entries(limit=10)
    last = entries[-1]
    assert last["action"] == "legitimacy_evaluated"
    payload = last["payload"]
    assert payload["legitimate"] is True
    assert payload["failed_dimensions"] == []
    assert payload["evidence_hashes"] == ["sha256:e1", "sha256:e2"]
    assert payload["evaluated_at"]

    lines = (tmp_path / "ledger" / "cryovant_journal.jsonl").read_text(encoding="utf-8").splitlines()
    tx = json.loads(lines[-1])
    assert tx["type"] == "LegitimacyEvaluation"
    assert tx["payload"]["legitimate"] is True


def test_evaluate_legitimacy_returns_failures_with_machine_reasons(tmp_path: Path, monkeypatch) -> None:
    _use_temp_ledgers(tmp_path, monkeypatch)
    record = {
        "id": "rec-002",
        "lineage": {},
        "signature_valid": False,
        "founders_law_satisfied": False,
        "capability_compliant": False,
        "trust_mode_compliant": False,
        "epoch": {"expected_epoch_id": "ep-2", "epoch_id": "ep-1"},
    }

    result = evaluate_legitimacy(record)

    assert result.legitimate is False
    assert len(result.failed_dimensions) == 6
    assert result.failure_reasons["lineage_completeness"] == ["missing_lineage_id", "missing_lineage_chain"]
    assert result.failure_reasons["signature_validity"] == ["signature_invalid"]
    assert result.failure_reasons["founders_law_satisfaction"] == ["founders_law_violation"]
    assert result.failure_reasons["capability_compliance"] == ["capability_policy_mismatch"]
    assert result.failure_reasons["trust_mode_compliance"] == ["trust_mode_violation"]
    assert result.failure_reasons["epoch_alignment"] == ["epoch_misaligned"]


def test_evaluate_legitimacy_uses_tier_thresholds(tmp_path: Path, monkeypatch) -> None:
    _use_temp_ledgers(tmp_path, monkeypatch)
    record = {
        "id": "rec-003",
        "tier": "PRODUCTION",
        "lineage": {"lineage_id": "lin-1", "parent_hash": "sha256:abc"},
        "signature": {"valid": True},
        "founders_law": {"satisfied": True},
        "capability": {"compliant": True},
        "trust_mode": {"compliant": True},
        "epoch": {"aligned": True},
    }
    result = evaluate_legitimacy(record)
    assert result.total_score == 1.0
    assert result.threshold == 0.95
    assert result.legitimate is True
