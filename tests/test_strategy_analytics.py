# SPDX-License-Identifier: Apache-2.0
"""Tests: StrategyAnalyticsEngine + RoutingHealthReport — Phase 22 / PR-22-01

Covers all 25+ acceptance criteria from PHASE_22_UPGRADE_PLAN.md:
- empty ledger, single-strategy, multi-strategy, window vs all-time
- drift detection, dominant strategy, stale detection
- health score bounds, status classification (green/amber/red)
- report_digest determinism, chain_valid flag
- StrategyAnalyticsError on invalid window_size
- strategy_stats sorted by strategy_id
- stale_strategy_ids sorted
- all 6 STRATEGY_TAXONOMY members always present
- no ledger mutation
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
pytestmark = pytest.mark.regression_standard

from runtime.intelligence.strategy import STRATEGY_TAXONOMY
from runtime.intelligence.strategy_analytics import (
    DRIFT_AMBER_THRESHOLD,
    DRIFT_RED_THRESHOLD,
    DOMINANT_SHARE_AMBER_THRESHOLD,
    DOMINANT_SHARE_RED_THRESHOLD,
    STALE_RED_FRACTION,
    WINDOW_SIZE_MAX,
    WINDOW_SIZE_MIN,
    RoutingHealthReport,
    StrategyAnalyticsEngine,
    StrategyAnalyticsError,
    StrategyWindowStats,
)
from runtime.intelligence.file_telemetry_sink import FileTelemetrySink, TelemetryLedgerReader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reader(tmp_path: Path, payloads: list[dict]) -> TelemetryLedgerReader:
    ledger = tmp_path / "tel.jsonl"
    sink = FileTelemetrySink(ledger, chain_verify_on_open=False)
    for p in payloads:
        sink.emit(p)
    return TelemetryLedgerReader(ledger)


def _engine(reader, window_size: int = 100) -> StrategyAnalyticsEngine:
    return StrategyAnalyticsEngine(reader, window_size=window_size)


def _approved(strategy_id: str) -> dict:
    return {"strategy_id": strategy_id, "outcome": "approved"}


def _rejected(strategy_id: str) -> dict:
    return {"strategy_id": strategy_id, "outcome": "rejected"}


# ---------------------------------------------------------------------------
# Empty ledger
# ---------------------------------------------------------------------------


class TestEmptyLedger:
    def test_empty_returns_valid_report(self, tmp_path):
        reader = _make_reader(tmp_path, [])
        report = _engine(reader).generate_report()
        assert isinstance(report, RoutingHealthReport)

    def test_empty_total_zero(self, tmp_path):
        reader = _make_reader(tmp_path, [])
        report = _engine(reader).generate_report()
        assert report.total_decisions == 0
        assert report.window_decisions == 0

    def test_empty_status_valid(self, tmp_path):
        reader = _make_reader(tmp_path, [])
        report = _engine(reader).generate_report()
        assert report.status in {"green", "amber", "red"}

    def test_empty_all_strategies_stale(self, tmp_path):
        reader = _make_reader(tmp_path, [])
        report = _engine(reader).generate_report()
        assert len(report.strategy_stats) == len(STRATEGY_TAXONOMY)
        assert all(s.stale for s in report.strategy_stats)


# ---------------------------------------------------------------------------
# Strategy stats completeness
# ---------------------------------------------------------------------------


class TestStrategyStatsCompleteness:
    def test_all_taxonomy_members_present(self, tmp_path):
        reader = _make_reader(tmp_path, [_approved("conservative_hold")])
        report = _engine(reader).generate_report()
        ids = {s.strategy_id for s in report.strategy_stats}
        assert ids == set(STRATEGY_TAXONOMY)

    def test_strategy_stats_sorted_by_id(self, tmp_path):
        reader = _make_reader(tmp_path, [_approved("safety_hardening")])
        report = _engine(reader).generate_report()
        ids = [s.strategy_id for s in report.strategy_stats]
        assert ids == sorted(ids)

    def test_stale_strategy_ids_sorted(self, tmp_path):
        reader = _make_reader(tmp_path, [_approved("conservative_hold")])
        report = _engine(reader).generate_report()
        assert list(report.stale_strategy_ids) == sorted(report.stale_strategy_ids)


# ---------------------------------------------------------------------------
# Win rate correctness
# ---------------------------------------------------------------------------


class TestWinRate:
    def test_single_approved(self, tmp_path):
        reader = _make_reader(tmp_path, [_approved("conservative_hold")])
        report = _engine(reader).generate_report()
        s = next(x for x in report.strategy_stats if x.strategy_id == "conservative_hold")
        assert s.win_rate == pytest.approx(1.0)
        assert s.total == 1
        assert s.approved == 1
        assert not s.stale

    def test_single_rejected(self, tmp_path):
        reader = _make_reader(tmp_path, [_rejected("conservative_hold")])
        report = _engine(reader).generate_report()
        s = next(x for x in report.strategy_stats if x.strategy_id == "conservative_hold")
        assert s.win_rate == pytest.approx(0.0)

    def test_mixed_win_rate(self, tmp_path):
        payloads = [_approved("safety_hardening")] * 3 + [_rejected("safety_hardening")]
        reader = _make_reader(tmp_path, payloads)
        report = _engine(reader).generate_report()
        s = next(x for x in report.strategy_stats if x.strategy_id == "safety_hardening")
        assert s.win_rate == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# Window vs all-time
# ---------------------------------------------------------------------------


class TestWindowStats:
    def test_window_smaller_than_total(self, tmp_path):
        # 20 approved then 10 rejected — window=10 should see only rejected
        payloads = [_approved("adaptive_self_mutate")] * 20 + [_rejected("adaptive_self_mutate")] * 10
        reader = _make_reader(tmp_path, payloads)
        report = _engine(reader, window_size=10).generate_report()
        s = next(x for x in report.strategy_stats if x.strategy_id == "adaptive_self_mutate")
        assert s.window_win_rate == pytest.approx(0.0)
        assert s.win_rate == pytest.approx(20 / 30)
        assert report.window_decisions == 10

    def test_window_larger_than_total_equals_alltime(self, tmp_path):
        payloads = [_approved("safety_hardening")] * 5
        reader = _make_reader(tmp_path, payloads)
        report = _engine(reader, window_size=100).generate_report()
        s = next(x for x in report.strategy_stats if x.strategy_id == "safety_hardening")
        assert s.window_win_rate == s.win_rate


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


class TestDrift:
    def test_no_drift_on_single_record(self, tmp_path):
        reader = _make_reader(tmp_path, [_approved("safety_hardening")])
        report = _engine(reader).generate_report()
        # all-time total < 2 → drift = 0.0
        s = next(x for x in report.strategy_stats if x.strategy_id == "safety_hardening")
        assert s.drift == pytest.approx(0.0)

    def test_drift_detected_on_regime_shift(self, tmp_path):
        # 50 approved then 50 rejected — window=50 sees all rejected
        payloads = [_approved("test_coverage_expansion")] * 50 + [_rejected("test_coverage_expansion")] * 50
        reader = _make_reader(tmp_path, payloads)
        report = _engine(reader, window_size=50).generate_report()
        s = next(x for x in report.strategy_stats if x.strategy_id == "test_coverage_expansion")
        # all-time win_rate = 0.5, window_win_rate = 0.0 → drift = 0.5
        assert s.drift == pytest.approx(0.5)
        assert report.drift_max >= 0.5


# ---------------------------------------------------------------------------
# Dominant strategy
# ---------------------------------------------------------------------------


class TestDominantStrategy:
    def test_dominant_strategy_detected(self, tmp_path):
        payloads = [_approved("conservative_hold")] * 9 + [_approved("safety_hardening")]
        reader = _make_reader(tmp_path, payloads)
        report = _engine(reader).generate_report()
        assert report.dominant_strategy == "conservative_hold"
        assert report.dominant_share == pytest.approx(0.9)

    def test_dominant_share_zero_on_empty(self, tmp_path):
        reader = _make_reader(tmp_path, [])
        report = _engine(reader).generate_report()
        assert report.dominant_share == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Stale detection
# ---------------------------------------------------------------------------


class TestStaleDetection:
    def test_unseen_strategy_is_stale(self, tmp_path):
        reader = _make_reader(tmp_path, [_approved("conservative_hold")])
        report = _engine(reader).generate_report()
        stale_ids = set(report.stale_strategy_ids)
        # every strategy except conservative_hold should be stale
        for sid in STRATEGY_TAXONOMY:
            if sid != "conservative_hold":
                assert sid in stale_ids

    def test_active_strategy_not_stale(self, tmp_path):
        reader = _make_reader(tmp_path, [_approved("safety_hardening")])
        report = _engine(reader).generate_report()
        s = next(x for x in report.strategy_stats if x.strategy_id == "safety_hardening")
        assert not s.stale


# ---------------------------------------------------------------------------
# Health score bounds
# ---------------------------------------------------------------------------


class TestHealthScore:
    def test_health_score_in_range(self, tmp_path):
        for n in range(0, 10):
            payloads = [_approved("conservative_hold")] * n
            reader = _make_reader(tmp_path / f"l{n}.jsonl", payloads)
            # use different path for each iteration
            sink = FileTelemetrySink(tmp_path / f"h{n}.jsonl", chain_verify_on_open=False)
            for p in payloads:
                sink.emit(p)
            r2 = TelemetryLedgerReader(tmp_path / f"h{n}.jsonl")
            report = StrategyAnalyticsEngine(r2).generate_report()
            assert 0.0 <= report.health_score <= 1.0


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------


class TestStatusClassification:
    def test_status_red_on_high_drift(self, tmp_path):
        # 100 approved then 100 rejected in window → drift = 0.5 > RED_THRESHOLD=0.4
        payloads = [_approved("test_coverage_expansion")] * 100 + [_rejected("test_coverage_expansion")] * 100
        reader = _make_reader(tmp_path, payloads)
        report = _engine(reader, window_size=100).generate_report()
        assert report.status == "red"

    def test_status_red_on_high_dominance(self, tmp_path):
        # 95% of window is one strategy → dominant_share > 0.90 → red
        payloads = [_approved("conservative_hold")] * 95 + [_approved("safety_hardening")] * 5
        reader = _make_reader(tmp_path, payloads)
        report = _engine(reader, window_size=100).generate_report()
        assert report.status == "red"

    def test_status_green_on_balanced_ledger(self, tmp_path):
        # balanced distribution across all 6 strategies
        payloads = []
        for sid in sorted(STRATEGY_TAXONOMY):
            payloads += [_approved(sid)] * 5 + [_rejected(sid)] * 2
        reader = _make_reader(tmp_path, payloads)
        report = _engine(reader, window_size=42).generate_report()
        # balanced → should not be red; green or amber
        assert report.status in {"green", "amber"}

    def test_status_is_valid_value(self, tmp_path):
        reader = _make_reader(tmp_path, [])
        report = _engine(reader).generate_report()
        assert report.status in {"green", "amber", "red"}


# ---------------------------------------------------------------------------
# report_digest determinism
# ---------------------------------------------------------------------------


class TestReportDigest:
    def test_digest_is_sha256_prefixed(self, tmp_path):
        reader = _make_reader(tmp_path, [_approved("conservative_hold")])
        report = _engine(reader).generate_report()
        assert report.report_digest.startswith("sha256:")
        assert len(report.report_digest) == len("sha256:") + 64

    def test_digest_deterministic_same_ledger(self, tmp_path):
        payloads = [_approved("safety_hardening"), _rejected("safety_hardening")]
        reader1 = _make_reader(tmp_path / "a.jsonl", payloads)
        reader2 = _make_reader(tmp_path / "b.jsonl", payloads)
        r1 = StrategyAnalyticsEngine(reader1, window_size=50).generate_report()
        r2 = StrategyAnalyticsEngine(reader2, window_size=50).generate_report()
        assert r1.report_digest == r2.report_digest

    def test_digest_changes_with_different_ledger(self, tmp_path):
        r1 = StrategyAnalyticsEngine(_make_reader(tmp_path / "c.jsonl", [_approved("conservative_hold")])).generate_report()
        r2 = StrategyAnalyticsEngine(_make_reader(tmp_path / "d.jsonl", [_rejected("conservative_hold")])).generate_report()
        assert r1.report_digest != r2.report_digest


# ---------------------------------------------------------------------------
# Chain validity
# ---------------------------------------------------------------------------


class TestChainValidity:
    def test_chain_valid_true_on_valid_ledger(self, tmp_path):
        reader = _make_reader(tmp_path, [_approved("conservative_hold")])
        report = _engine(reader).generate_report()
        assert report.ledger_chain_valid is True

    def test_chain_valid_false_on_tampered_ledger(self, tmp_path):
        ledger = tmp_path / "tampered.jsonl"
        sink = FileTelemetrySink(ledger, chain_verify_on_open=False)
        sink.emit({"strategy_id": "conservative_hold", "outcome": "approved"})
        # tamper: overwrite with garbage
        ledger.write_text("not-valid-json\n")
        reader = TelemetryLedgerReader(ledger)
        report = StrategyAnalyticsEngine(reader).generate_report()
        assert report.ledger_chain_valid is False


# ---------------------------------------------------------------------------
# Invalid window_size
# ---------------------------------------------------------------------------


class TestInvalidWindowSize:
    def test_window_size_too_small_raises(self, tmp_path):
        reader = _make_reader(tmp_path, [])
        with pytest.raises(StrategyAnalyticsError):
            StrategyAnalyticsEngine(reader, window_size=WINDOW_SIZE_MIN - 1)

    def test_window_size_too_large_raises(self, tmp_path):
        reader = _make_reader(tmp_path, [])
        with pytest.raises(StrategyAnalyticsError):
            StrategyAnalyticsEngine(reader, window_size=WINDOW_SIZE_MAX + 1)

    def test_boundary_min_accepted(self, tmp_path):
        reader = _make_reader(tmp_path, [])
        engine = StrategyAnalyticsEngine(reader, window_size=WINDOW_SIZE_MIN)
        assert engine.generate_report().window_size == WINDOW_SIZE_MIN

    def test_boundary_max_accepted(self, tmp_path):
        reader = _make_reader(tmp_path, [])
        engine = StrategyAnalyticsEngine(reader, window_size=WINDOW_SIZE_MAX)
        assert engine.generate_report().window_size == WINDOW_SIZE_MAX


# ---------------------------------------------------------------------------
# No ledger mutation
# ---------------------------------------------------------------------------


class TestNoLedgerMutation:
    def test_generate_does_not_write_to_ledger(self, tmp_path):
        ledger = tmp_path / "immutable.jsonl"
        sink = FileTelemetrySink(ledger, chain_verify_on_open=False)
        sink.emit({"strategy_id": "conservative_hold", "outcome": "approved"})
        size_before = ledger.stat().st_size
        reader = TelemetryLedgerReader(ledger)
        StrategyAnalyticsEngine(reader).generate_report()
        assert ledger.stat().st_size == size_before


class TestUnifiedReaderContract:
    def test_report_identical_for_unified_and_legacy_reader_contracts(self):
        payloads = [
            _approved("conservative_hold"),
            _rejected("conservative_hold"),
            _approved("safety_hardening"),
            _approved("safety_hardening"),
            _rejected("exploratory_probe"),
        ]

        class _LegacyReader:
            def __init__(self, items):
                self._items = list(items)

            def _all_payloads(self):
                return list(self._items)

            def verify_chain(self):
                return True

        class _UnifiedReader:
            def __init__(self, items):
                self._items = list(items)

            def payloads_chain_snapshot(self):
                return (list(self._items), True, len(self._items))

        legacy_report = StrategyAnalyticsEngine(_LegacyReader(payloads), window_size=10).generate_report()
        unified_report = StrategyAnalyticsEngine(_UnifiedReader(payloads), window_size=10).generate_report()
        assert legacy_report == unified_report

    def test_unified_reader_avoids_duplicate_legacy_calls(self):
        payloads = [_approved("conservative_hold")] * 12

        class _CountingReader:
            def __init__(self, items):
                self._items = list(items)
                self.snapshot_calls = 0
                self.all_payload_calls = 0
                self.verify_calls = 0

            def payloads_chain_snapshot(self):
                self.snapshot_calls += 1
                return (list(self._items), True, len(self._items))

            def _all_payloads(self):
                self.all_payload_calls += 1
                return list(self._items)

            def verify_chain(self):
                self.verify_calls += 1
                return True

        reader = _CountingReader(payloads)
        StrategyAnalyticsEngine(reader, window_size=10).generate_report()
        assert reader.snapshot_calls == 1
        assert reader.all_payload_calls == 0
        assert reader.verify_calls == 0
