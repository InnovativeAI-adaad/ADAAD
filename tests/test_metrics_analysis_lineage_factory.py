# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from runtime.metrics_analysis import _build_lineage_ledger


def test_build_lineage_ledger_uses_explicit_path(tmp_path: Path) -> None:
    ledger_path = tmp_path / "lineage_v2.jsonl"

    ledger = _build_lineage_ledger(ledger_path)

    assert ledger.ledger_path == ledger_path
    assert ledger_path.parent.exists()


def test_build_lineage_ledger_uses_env_path(tmp_path: Path, monkeypatch) -> None:
    ledger_path = tmp_path / "custom" / "lineage_v2.jsonl"
    monkeypatch.setenv("ADAAD_LINEAGE_PATH", str(ledger_path))

    ledger = _build_lineage_ledger()

    assert ledger.ledger_path == ledger_path
    assert ledger_path.parent.exists()


def test_build_lineage_ledger_creates_parent_directory(tmp_path: Path) -> None:
    ledger_path = tmp_path / "nested" / "path" / "lineage_v2.jsonl"

    assert not ledger_path.parent.exists()

    ledger = _build_lineage_ledger(ledger_path)

    assert ledger.ledger_path == ledger_path
    assert ledger_path.parent.exists()
