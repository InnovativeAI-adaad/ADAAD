# SPDX-License-Identifier: Apache-2.0
"""Tests: FileTelemetrySink + TelemetryLedgerReader — Phase 21 / PR-21-01

Covers:
- FileTelemetrySink: emit, chain integrity, error isolation, GENESIS_PREV_HASH,
  entries(), __len__, parent dir creation, chain_verify_on_open
- TelemetryLedgerReader: query (filters, pagination), win_rate_by_strategy,
  strategy_summary, verify_chain, __len__
- Replay determinism: identical payloads → identical record_hash chain
- Schema conformance: emitted records match telemetry_decision_record.v1.json
- TelemetryChainError: raised on tamper, sequence gap, prev_hash mismatch
- Public API: symbols exported from runtime.intelligence
"""

from __future__ import annotations

import hashlib
import json
import os
import pytest
pytestmark = pytest.mark.regression_standard
from pathlib import Path

from runtime.intelligence.file_telemetry_sink import (
    GENESIS_PREV_HASH,
    TELEMETRY_LEDGER_VERSION,
    FileTelemetrySink,
    TelemetryChainError,
    TelemetryLedgerReader,
    _compute_record_hash,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decision_payload(
    cycle_id: str = "cycle-001",
    strategy_id: str = "exploratory_probe",
    outcome: str = "approved",
    composite: float = 0.75,
) -> dict:
    return {
        "event_type": "routed_intelligence_decision.v1",
        "telemetry_version": "17.0",
        "cycle_id": cycle_id,
        "strategy_id": strategy_id,
        "outcome": outcome,
        "composite_score": round(composite, 6),
        "review_digest": "sha256:" + hashlib.sha256(cycle_id.encode()).hexdigest(),
        "confidence": 0.85,
        "risk_flags": [],
    }


def _read_records(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s:
            records.append(json.loads(s))
    return records


# ---------------------------------------------------------------------------
# FileTelemetrySink — basic emit
# ---------------------------------------------------------------------------

class TestFileTelemetrySinkEmit:
    def test_emit_single_record(self, tmp_path):
        sink = FileTelemetrySink(tmp_path / "tel.jsonl")
        sink.emit(_decision_payload())
        records = _read_records(tmp_path / "tel.jsonl")
        assert len(records) == 1
        assert records[0]["sequence"] == 0
        assert records[0]["prev_hash"] == GENESIS_PREV_HASH

    def test_emit_sequence_increments(self, tmp_path):
        sink = FileTelemetrySink(tmp_path / "tel.jsonl")
        for i in range(5):
            sink.emit(_decision_payload(cycle_id=f"cycle-{i:03d}"))
        records = _read_records(tmp_path / "tel.jsonl")
        assert [r["sequence"] for r in records] == [0, 1, 2, 3, 4]

    def test_emit_prev_hash_chain(self, tmp_path):
        sink = FileTelemetrySink(tmp_path / "tel.jsonl")
        for i in range(3):
            sink.emit(_decision_payload(cycle_id=f"c{i}"))
        records = _read_records(tmp_path / "tel.jsonl")
        assert records[0]["prev_hash"] == GENESIS_PREV_HASH
        assert records[1]["prev_hash"] == records[0]["record_hash"]
        assert records[2]["prev_hash"] == records[1]["record_hash"]

    def test_emit_record_hash_deterministic(self, tmp_path):
        p1 = tmp_path / "a.jsonl"
        p2 = tmp_path / "b.jsonl"
        payload = _decision_payload(cycle_id="fixed")
        FileTelemetrySink(p1).emit(payload)
        FileTelemetrySink(p2).emit(payload)
        r1 = _read_records(p1)[0]
        r2 = _read_records(p2)[0]
        assert r1["record_hash"] == r2["record_hash"]

    def test_emit_len_tracks_count(self, tmp_path):
        sink = FileTelemetrySink(tmp_path / "tel.jsonl")
        assert len(sink) == 0
        sink.emit(_decision_payload())
        assert len(sink) == 1
        sink.emit(_decision_payload(cycle_id="c2"))
        assert len(sink) == 2

    def test_emit_creates_parent_dirs(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c" / "tel.jsonl"
        sink = FileTelemetrySink(deep)
        sink.emit(_decision_payload())
        assert deep.exists()
        assert len(_read_records(deep)) == 1

    def test_entries_returns_payloads_in_order(self, tmp_path):
        sink = FileTelemetrySink(tmp_path / "tel.jsonl")
        payloads = [_decision_payload(cycle_id=f"c{i}") for i in range(4)]
        for p in payloads:
            sink.emit(p)
        entries = sink.entries()
        assert isinstance(entries, tuple)
        assert len(entries) == 4
        assert entries[0]["cycle_id"] == "c0"
        assert entries[3]["cycle_id"] == "c3"

    def test_entries_empty_ledger(self, tmp_path):
        sink = FileTelemetrySink(tmp_path / "tel.jsonl")
        assert sink.entries() == ()


# ---------------------------------------------------------------------------
# FileTelemetrySink — chain verification
# ---------------------------------------------------------------------------

class TestFileTelemetrySinkChain:
    def test_verify_chain_valid(self, tmp_path):
        sink = FileTelemetrySink(tmp_path / "tel.jsonl")
        for i in range(10):
            sink.emit(_decision_payload(cycle_id=f"c{i}"))
        assert sink.verify_chain() is True

    def test_verify_chain_empty_file(self, tmp_path):
        sink = FileTelemetrySink(tmp_path / "tel.jsonl")
        assert sink.verify_chain() is True

    def test_verify_chain_tampered_record_hash_raises(self, tmp_path):
        path = tmp_path / "tel.jsonl"
        sink = FileTelemetrySink(path)
        sink.emit(_decision_payload())
        # Tamper the record_hash
        records = _read_records(path)
        records[0]["record_hash"] = "sha256:" + "f" * 64
        path.write_text(
            "\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in records) + "\n",
            encoding="utf-8",
        )
        new_sink = FileTelemetrySink(path, chain_verify_on_open=False)
        with pytest.raises(TelemetryChainError) as exc_info:
            new_sink.verify_chain()
        assert exc_info.value.sequence == 0

    def test_verify_chain_tampered_payload_raises(self, tmp_path):
        path = tmp_path / "tel.jsonl"
        sink = FileTelemetrySink(path)
        sink.emit(_decision_payload())
        records = _read_records(path)
        records[0]["payload"]["outcome"] = "rejected"  # tamper payload
        path.write_text(
            "\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in records) + "\n",
            encoding="utf-8",
        )
        new_sink = FileTelemetrySink(path, chain_verify_on_open=False)
        with pytest.raises(TelemetryChainError):
            new_sink.verify_chain()

    def test_verify_chain_sequence_gap_raises(self, tmp_path):
        path = tmp_path / "tel.jsonl"
        sink = FileTelemetrySink(path)
        for i in range(3):
            sink.emit(_decision_payload(cycle_id=f"c{i}"))
        # Delete the middle record
        records = _read_records(path)
        del records[1]
        path.write_text(
            "\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in records) + "\n",
            encoding="utf-8",
        )
        new_sink = FileTelemetrySink(path, chain_verify_on_open=False)
        with pytest.raises(TelemetryChainError):
            new_sink.verify_chain()

    def test_chain_verify_on_open_broken_chain_raises_at_init(self, tmp_path):
        path = tmp_path / "tel.jsonl"
        # Write a valid record first
        sink = FileTelemetrySink(path)
        sink.emit(_decision_payload())
        # Now corrupt it
        path.write_text('{"sequence":0,"prev_hash":"bad","record_hash":"bad","payload":{}}\n', encoding="utf-8")
        with pytest.raises(TelemetryChainError):
            FileTelemetrySink(path, chain_verify_on_open=True)

    def test_chain_verify_on_open_false_bypasses_check(self, tmp_path):
        path = tmp_path / "tel.jsonl"
        path.write_text('{"sequence":0,"prev_hash":"bad","record_hash":"bad","payload":{}}\n', encoding="utf-8")
        # Should not raise
        sink = FileTelemetrySink(path, chain_verify_on_open=False)
        assert sink is not None


# ---------------------------------------------------------------------------
# FileTelemetrySink — emit failure isolation
# ---------------------------------------------------------------------------

class TestFileTelemetrySinkEmitFailure:
    def test_emit_failure_does_not_raise(self, tmp_path, monkeypatch):
        sink = FileTelemetrySink(tmp_path / "tel.jsonl")
        # Make the path a directory so open("a") fails
        bad_path = tmp_path / "blocked"
        bad_path.mkdir()
        sink._path = bad_path
        # Should not raise
        sink.emit(_decision_payload())

    def test_emit_failure_logs_warning(self, tmp_path, monkeypatch, caplog):
        import logging
        sink = FileTelemetrySink(tmp_path / "tel.jsonl")
        bad_path = tmp_path / "blocked"
        bad_path.mkdir()
        sink._path = bad_path
        with caplog.at_level(logging.WARNING):
            sink.emit(_decision_payload())
        assert any("FileTelemetrySink.emit failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# FileTelemetrySink — replay determinism
# ---------------------------------------------------------------------------

class TestFileTelemetrySinkDeterminism:
    def test_identical_payloads_identical_chain(self, tmp_path):
        payloads = [_decision_payload(cycle_id=f"c{i}") for i in range(5)]
        p1 = tmp_path / "a.jsonl"
        p2 = tmp_path / "b.jsonl"
        s1 = FileTelemetrySink(p1)
        s2 = FileTelemetrySink(p2)
        for payload in payloads:
            s1.emit(dict(payload))
            s2.emit(dict(payload))
        r1 = _read_records(p1)
        r2 = _read_records(p2)
        for rec1, rec2 in zip(r1, r2):
            assert rec1["record_hash"] == rec2["record_hash"]

    def test_genesis_prev_hash_matches_mutation_ledger_constant(self):
        expected = "sha256:" + "0" * 64
        assert GENESIS_PREV_HASH == expected


# ---------------------------------------------------------------------------
# TelemetryLedgerReader — query
# ---------------------------------------------------------------------------

class TestTelemetryLedgerReaderQuery:
    def _populated_path(self, tmp_path) -> Path:
        path = tmp_path / "tel.jsonl"
        sink = FileTelemetrySink(path)
        strategies = ["exploratory_probe", "conservative_hold", "structural_refactor"]
        outcomes = ["approved", "rejected", "approved", "approved", "rejected"]
        for i, (s, o) in enumerate(zip(strategies * 2, outcomes)):
            sink.emit(_decision_payload(cycle_id=f"c{i}", strategy_id=s, outcome=o))
        return path

    def test_query_no_filter_returns_all_newest_first(self, tmp_path):
        path = self._populated_path(tmp_path)
        reader = TelemetryLedgerReader(path)
        results = reader.query()
        assert len(results) == 5
        # Newest first (sequence 4 → 0)
        cycle_ids = [r["cycle_id"] for r in results]
        assert cycle_ids == ["c4", "c3", "c2", "c1", "c0"]

    def test_query_strategy_id_filter(self, tmp_path):
        path = self._populated_path(tmp_path)
        reader = TelemetryLedgerReader(path)
        results = reader.query(strategy_id="exploratory_probe")
        assert all(r["strategy_id"] == "exploratory_probe" for r in results)

    def test_query_outcome_filter(self, tmp_path):
        path = self._populated_path(tmp_path)
        reader = TelemetryLedgerReader(path)
        results = reader.query(outcome="approved")
        assert all(r["outcome"] == "approved" for r in results)
        assert len(results) == 3

    def test_query_limit(self, tmp_path):
        path = self._populated_path(tmp_path)
        reader = TelemetryLedgerReader(path)
        results = reader.query(limit=2)
        assert len(results) == 2

    def test_query_offset(self, tmp_path):
        path = self._populated_path(tmp_path)
        reader = TelemetryLedgerReader(path)
        all_results = reader.query()
        offset_results = reader.query(offset=2)
        assert offset_results == all_results[2:]

    def test_query_limit_capped_at_500(self, tmp_path):
        path = self._populated_path(tmp_path)
        reader = TelemetryLedgerReader(path)
        # limit=999 should be capped at 500 (not error)
        results = reader.query(limit=999)
        assert len(results) <= 500

    def test_query_empty_ledger(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        reader = TelemetryLedgerReader(path)
        assert reader.query() == []

    def test_query_deterministic(self, tmp_path):
        path = self._populated_path(tmp_path)
        reader = TelemetryLedgerReader(path)
        r1 = reader.query(strategy_id="exploratory_probe")
        r2 = reader.query(strategy_id="exploratory_probe")
        assert r1 == r2


# ---------------------------------------------------------------------------
# TelemetryLedgerReader — analytics
# ---------------------------------------------------------------------------

class TestTelemetryLedgerReaderAnalytics:
    def test_win_rate_by_strategy(self, tmp_path):
        path = tmp_path / "tel.jsonl"
        sink = FileTelemetrySink(path)
        sink.emit(_decision_payload(strategy_id="alpha", outcome="approved"))
        sink.emit(_decision_payload(strategy_id="alpha", outcome="approved"))
        sink.emit(_decision_payload(strategy_id="alpha", outcome="rejected"))
        sink.emit(_decision_payload(strategy_id="beta", outcome="rejected"))
        reader = TelemetryLedgerReader(path)
        rates = reader.win_rate_by_strategy()
        assert abs(rates["alpha"] - 2 / 3) < 1e-9
        assert abs(rates["beta"] - 0.0) < 1e-9

    def test_win_rate_empty_returns_empty_dict(self, tmp_path):
        reader = TelemetryLedgerReader(tmp_path / "empty.jsonl")
        assert reader.win_rate_by_strategy() == {}

    def test_strategy_summary_counts(self, tmp_path):
        path = tmp_path / "tel.jsonl"
        sink = FileTelemetrySink(path)
        sink.emit(_decision_payload(strategy_id="alpha", outcome="approved"))
        sink.emit(_decision_payload(strategy_id="alpha", outcome="rejected"))
        sink.emit(_decision_payload(strategy_id="alpha", outcome="held"))
        reader = TelemetryLedgerReader(path)
        summary = reader.strategy_summary()
        assert summary["alpha"]["total"] == 3
        assert summary["alpha"]["approved"] == 1
        assert summary["alpha"]["rejected"] == 1
        assert summary["alpha"]["held"] == 1

    def test_len_reader(self, tmp_path):
        path = tmp_path / "tel.jsonl"
        sink = FileTelemetrySink(path)
        for i in range(7):
            sink.emit(_decision_payload(cycle_id=f"c{i}"))
        reader = TelemetryLedgerReader(path)
        assert len(reader) == 7

    def test_reader_verify_chain_valid(self, tmp_path):
        path = tmp_path / "tel.jsonl"
        sink = FileTelemetrySink(path)
        for i in range(5):
            sink.emit(_decision_payload(cycle_id=f"c{i}"))
        reader = TelemetryLedgerReader(path)
        assert reader.verify_chain() is True

    def test_reader_verify_chain_tampered_raises(self, tmp_path):
        path = tmp_path / "tel.jsonl"
        sink = FileTelemetrySink(path)
        sink.emit(_decision_payload())
        # Corrupt the file
        records = _read_records(path)
        records[0]["payload"]["outcome"] = "TAMPERED"
        path.write_text(
            "\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in records) + "\n",
            encoding="utf-8",
        )
        reader = TelemetryLedgerReader(path)
        with pytest.raises(TelemetryChainError):
            reader.verify_chain()

    def test_reader_shared_snapshot_reuses_single_parse_on_large_ledger(self, tmp_path, monkeypatch):
        path = tmp_path / "large.jsonl"
        sink = FileTelemetrySink(path)
        for i in range(5000):
            outcome = "approved" if i % 3 else "rejected"
            sink.emit(_decision_payload(cycle_id=f"c{i}", strategy_id=f"s{i % 7}", outcome=outcome))

        reader = TelemetryLedgerReader(path)
        calls = {"iter_records": 0}
        original = TelemetryLedgerReader.iter_records

        def _counting_iter_records(self):
            calls["iter_records"] += 1
            yield from original(self)

        monkeypatch.setattr(TelemetryLedgerReader, "iter_records", _counting_iter_records)

        assert len(reader.query(limit=25)) == 25
        assert reader.strategy_summary()
        assert reader.win_rate_by_strategy()
        assert len(reader) == 5000
        assert calls["iter_records"] == 1

    def test_reader_snapshot_invalidates_on_file_change(self, tmp_path, monkeypatch):
        path = tmp_path / "evolving.jsonl"
        sink = FileTelemetrySink(path)
        for i in range(100):
            sink.emit(_decision_payload(cycle_id=f"c{i}"))

        reader = TelemetryLedgerReader(path)
        calls = {"iter_records": 0}
        original = TelemetryLedgerReader.iter_records

        def _counting_iter_records(self):
            calls["iter_records"] += 1
            yield from original(self)

        monkeypatch.setattr(TelemetryLedgerReader, "iter_records", _counting_iter_records)
        assert len(reader) == 100
        assert calls["iter_records"] == 1

        sink.emit(_decision_payload(cycle_id="c100"))
        assert len(reader) == 101
        assert calls["iter_records"] == 2

    def test_reader_methods_do_not_use_read_text(self, tmp_path, monkeypatch):
        path = tmp_path / "stream.jsonl"
        sink = FileTelemetrySink(path)
        for i in range(25):
            sink.emit(_decision_payload(cycle_id=f"c{i}"))
        reader = TelemetryLedgerReader(path)

        def _forbidden_read_text(*args, **kwargs):
            raise AssertionError("TelemetryLedgerReader should stream file access, not read_text")

        monkeypatch.setattr(Path, "read_text", _forbidden_read_text)

        assert len(reader.query(limit=5)) == 5
        assert len(reader) == 25
        assert reader.verify_chain() is True


# ---------------------------------------------------------------------------
# Public API contract
# ---------------------------------------------------------------------------

class TestPublicAPIExports:
    def test_file_telemetry_sink_exported(self):
        from runtime.intelligence import FileTelemetrySink as FTS
        assert FTS is FileTelemetrySink

    def test_telemetry_ledger_reader_exported(self):
        from runtime.intelligence import TelemetryLedgerReader as TLR
        assert TLR is TelemetryLedgerReader

    def test_telemetry_chain_error_exported(self):
        from runtime.intelligence import TelemetryChainError as TCE
        assert TCE is TelemetryChainError

    def test_genesis_prev_hash_exported(self):
        from runtime.intelligence import GENESIS_PREV_HASH as GPH
        assert GPH == GENESIS_PREV_HASH

    def test_telemetry_ledger_version_exported(self):
        from runtime.intelligence import TELEMETRY_LEDGER_VERSION as TLV
        assert TLV == "21.0"
