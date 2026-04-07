# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

from runtime.oracle_ledger import OracleLedger
from runtime.oracle_memory import summarize_oracle_memory


def test_oracle_memory_detects_recurring_risk_motifs() -> None:
    records = [
        {"query": "divergence risk", "query_type": "divergence_recent"},
        {"query": "divergence trend", "query_type": "divergence_recent"},
        {"query": "release blockers", "query_type": "gate_violations"},
        {"query": "release blockers again", "query_type": "gate_violations"},
    ]
    summary = summarize_oracle_memory(records, window=10)
    motifs = summary["trend_indicators"]["recurring_risk_motifs"]
    assert any(m["motif"] == "divergence_concerns" for m in motifs)
    assert any(m["motif"] == "blocker_families" for m in motifs)


def test_oracle_memory_summary_from_ledger_records(tmp_path: Path) -> None:
    ledger = OracleLedger(path=tmp_path / "oracle_memory.jsonl")
    for query, qtype in (
        ("divergence concern", "divergence_recent"),
        ("blocker status", "gate_violations"),
        ("strategy opportunity", "strategy_projection"),
    ):
        ledger.append(query=query, answer={"query_type": qtype, "message": query}, events=[])
    records = ledger.replay(limit=10)
    summary = summarize_oracle_memory(records, window=10)
    assert summary["window"] == 3
    assert "since_last_10_summary" in summary
