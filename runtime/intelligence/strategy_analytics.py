# SPDX-License-Identifier: Apache-2.0
"""StrategyAnalyticsEngine + RoutingHealthReport — Phase 22

Higher-order analytics over the Phase 21 TelemetryLedgerReader surface.
Computes rolling-window win rates, drift detection, staleness flags, and a
structured RoutingHealthReport with health classification (green/amber/red).

Design invariants:
- Read-only: never writes to the telemetry ledger.
- Deterministic: same ledger state + same parameters → identical RoutingHealthReport
  and report_digest.
- No GovernanceGate reference: analytics are advisory/observability only.
- Empty ledger is valid: returns a zero-data green report.
- All 6 STRATEGY_TAXONOMY members always appear in strategy_stats (even if unseen).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from runtime.intelligence.strategy import STRATEGY_TAXONOMY

# ---------------------------------------------------------------------------
# Health classification thresholds (constants — never dynamic)
# ---------------------------------------------------------------------------

HEALTH_GREEN_MIN_SCORE: float = 0.65
HEALTH_AMBER_MIN_SCORE: float = 0.35

DOMINANT_SHARE_AMBER_THRESHOLD: float = 0.75
DOMINANT_SHARE_RED_THRESHOLD: float = 0.90
DRIFT_AMBER_THRESHOLD: float = 0.20
DRIFT_RED_THRESHOLD: float = 0.40
STALE_AMBER_FRACTION: float = 0.34
STALE_RED_FRACTION: float = 0.60

WINDOW_SIZE_MIN: int = 10
WINDOW_SIZE_MAX: int = 10_000

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StrategyAnalyticsError(Exception):
    """Raised when StrategyAnalyticsEngine cannot produce a valid report."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StrategyWindowStats:
    """Per-strategy rolling-window statistics."""

    strategy_id: str
    window_size: int
    total: int
    approved: int
    win_rate: float
    window_win_rate: float
    drift: float
    stale: bool
    last_seen_sequence: int


@dataclass(frozen=True)
class RoutingHealthReport:
    """Structured routing health classification — deterministic, advisory only."""

    status: str
    health_score: float
    strategy_stats: tuple
    dominant_strategy: "str | None"
    dominant_share: float
    stale_strategy_ids: tuple
    drift_max: float
    window_size: int
    total_decisions: int
    window_decisions: int
    ledger_chain_valid: bool
    report_digest: str


# ---------------------------------------------------------------------------
# Digest helper
# ---------------------------------------------------------------------------


def _compute_report_digest(report: RoutingHealthReport) -> str:
    """Deterministic SHA-256 digest of canonical report fields."""
    digest_input = json.dumps(
        {
            "status": report.status,
            "health_score": round(report.health_score, 8),
            "dominant_strategy": report.dominant_strategy,
            "dominant_share": round(report.dominant_share, 8),
            "drift_max": round(report.drift_max, 8),
            "window_size": report.window_size,
            "total_decisions": report.total_decisions,
            "window_decisions": report.window_decisions,
            "stale_strategy_ids": list(report.stale_strategy_ids),
            "strategy_stats": [
                {
                    "strategy_id": s.strategy_id,
                    "win_rate": round(s.win_rate, 8),
                    "window_win_rate": round(s.window_win_rate, 8),
                    "drift": round(s.drift, 8),
                    "stale": s.stale,
                }
                for s in report.strategy_stats
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(digest_input.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Health classification
# ---------------------------------------------------------------------------


def _classify_status(
    health_score: float,
    dominant_share: float,
    drift_max: float,
    stale_fraction: float,
) -> str:
    """Evaluate status in priority order — first match wins."""
    if drift_max > DRIFT_RED_THRESHOLD:
        return "red"
    if dominant_share > DOMINANT_SHARE_RED_THRESHOLD:
        return "red"
    if stale_fraction > STALE_RED_FRACTION:
        return "red"
    if health_score < HEALTH_AMBER_MIN_SCORE:
        return "red"
    if drift_max > DRIFT_AMBER_THRESHOLD:
        return "amber"
    if dominant_share > DOMINANT_SHARE_AMBER_THRESHOLD:
        return "amber"
    if stale_fraction > STALE_AMBER_FRACTION:
        return "amber"
    if health_score < HEALTH_GREEN_MIN_SCORE:
        return "amber"
    return "green"


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# StrategyAnalyticsEngine
# ---------------------------------------------------------------------------


class StrategyAnalyticsEngine:
    """Compute RoutingHealthReport from a TelemetryLedgerReader.

    Parameters
    ----------
    reader:
        A TelemetryLedgerReader instance (or any object with a compatible
        payloads_chain_snapshot interface — duck-typed for testability.
        Legacy _all_payloads/verify_chain and entries()-based adapters are
        still supported for backward compatibility.
    window_size:
        Number of most-recent decisions included in the rolling window.
        Must be in [WINDOW_SIZE_MIN, WINDOW_SIZE_MAX] = [10, 10_000].
    strategy_taxonomy:
        The set of known strategy IDs. Defaults to STRATEGY_TAXONOMY.
        All members always appear in strategy_stats, even if unseen.
    """

    def __init__(
        self,
        reader: Any,
        *,
        window_size: int = 100,
        strategy_taxonomy: "frozenset[str] | None" = None,
    ) -> None:
        if not (WINDOW_SIZE_MIN <= window_size <= WINDOW_SIZE_MAX):
            raise StrategyAnalyticsError(
                f"window_size must be in [{WINDOW_SIZE_MIN}, {WINDOW_SIZE_MAX}]; got {window_size}"
            )
        self._reader = reader
        self._window_size = window_size
        self._taxonomy: frozenset[str] = strategy_taxonomy if strategy_taxonomy is not None else STRATEGY_TAXONOMY

    def generate_report(self) -> RoutingHealthReport:
        """Generate a deterministic RoutingHealthReport.

        Reads the ledger once; computes all-time and window stats; classifies health.
        Never writes to the ledger. Never raises on empty ledger.
        """
        # --- fetch payloads + chain status with a single reader pass when available ---
        all_payloads: list[dict] = []
        chain_valid = False
        _record_count = 0
        if hasattr(self._reader, "payloads_chain_snapshot"):
            try:
                all_payloads, chain_valid, _record_count = self._reader.payloads_chain_snapshot()
            except Exception:
                all_payloads = []
                chain_valid = False
                _record_count = 0
        else:
            # legacy compatibility for older/ad-hoc reader adapters
            try:
                all_payloads = list(getattr(self._reader, "_all_payloads", lambda: [])())
            except Exception:
                all_payloads = []
            if not all_payloads:
                try:
                    all_payloads = [
                        r["payload"] if "payload" in r else r
                        for r in (self._reader.entries() if hasattr(self._reader, "entries") else [])
                    ]
                except Exception:
                    all_payloads = []
            try:
                chain_valid = self._reader.verify_chain()
            except Exception:
                chain_valid = False

        total_decisions = len(all_payloads)

        # determine window slice
        window_payloads = all_payloads[-self._window_size:] if total_decisions > 0 else []
        window_decisions = len(window_payloads)

        # --- compute all-time counts per strategy ---
        all_time_total: dict[str, int] = {sid: 0 for sid in self._taxonomy}
        all_time_approved: dict[str, int] = {sid: 0 for sid in self._taxonomy}
        all_time_last_seq: dict[str, int] = {sid: -1 for sid in self._taxonomy}

        for idx, payload in enumerate(all_payloads):
            sid = payload.get("strategy_id", "")
            if sid not in self._taxonomy:
                continue
            all_time_total[sid] += 1
            if payload.get("outcome") == "approved":
                all_time_approved[sid] += 1
            all_time_last_seq[sid] = idx  # sequence index within full list

        # --- compute window counts per strategy ---
        window_total: dict[str, int] = {sid: 0 for sid in self._taxonomy}
        window_approved: dict[str, int] = {sid: 0 for sid in self._taxonomy}
        window_start_idx = max(0, total_decisions - self._window_size)

        for payload in window_payloads:
            sid = payload.get("strategy_id", "")
            if sid not in self._taxonomy:
                continue
            window_total[sid] += 1
            if payload.get("outcome") == "approved":
                window_approved[sid] += 1

        # --- build StrategyWindowStats per strategy ---
        stats_list: list[StrategyWindowStats] = []
        for sid in sorted(self._taxonomy):
            at_total = all_time_total[sid]
            at_approved = all_time_approved[sid]
            w_total = window_total[sid]
            w_approved = window_approved[sid]

            win_rate = at_approved / at_total if at_total > 0 else 0.0
            window_win_rate = w_approved / w_total if w_total > 0 else 0.0
            drift = abs(window_win_rate - win_rate) if at_total >= 2 else 0.0
            stale = w_total == 0
            last_seq = all_time_last_seq[sid]

            stats_list.append(
                StrategyWindowStats(
                    strategy_id=sid,
                    window_size=self._window_size,
                    total=at_total,
                    approved=at_approved,
                    win_rate=win_rate,
                    window_win_rate=window_win_rate,
                    drift=drift,
                    stale=stale,
                    last_seen_sequence=last_seq,
                )
            )

        # --- dominant strategy in window ---
        dominant_strategy: "str | None" = None
        dominant_share: float = 0.0
        if window_decisions > 0:
            max_sid = max(sorted(self._taxonomy), key=lambda s: window_total[s])
            dominant_strategy = max_sid
            dominant_share = window_total[max_sid] / window_decisions

        # --- aggregate metrics ---
        stale_ids = tuple(sorted(s.strategy_id for s in stats_list if s.stale))
        drift_max = max((s.drift for s in stats_list), default=0.0)
        taxonomy_size = len(self._taxonomy)
        stale_fraction = len(stale_ids) / taxonomy_size if taxonomy_size > 0 else 0.0

        # --- health score ---
        non_stale = [s for s in stats_list if not s.stale]
        win_rate_component = (
            sum(s.window_win_rate for s in non_stale) / len(non_stale)
            if non_stale else 1.0
        )
        distribution_penalty = dominant_share * 0.3
        staleness_penalty = stale_fraction * 0.2
        drift_penalty = min(drift_max, 1.0) * 0.2
        health_score = _clamp(
            win_rate_component - distribution_penalty - staleness_penalty - drift_penalty,
            0.0,
            1.0,
        )

        # --- status ---
        status = _classify_status(health_score, dominant_share, drift_max, stale_fraction)

        # --- build report (without digest first) ---
        partial = RoutingHealthReport(
            status=status,
            health_score=health_score,
            strategy_stats=tuple(stats_list),
            dominant_strategy=dominant_strategy,
            dominant_share=dominant_share,
            stale_strategy_ids=stale_ids,
            drift_max=drift_max,
            window_size=self._window_size,
            total_decisions=total_decisions,
            window_decisions=window_decisions,
            ledger_chain_valid=chain_valid,
            report_digest="",  # placeholder; recomputed below
        )

        # compute digest on the complete partial (digest field excluded from input)
        digest = _compute_report_digest(partial)

        # return final frozen report with digest filled in
        return RoutingHealthReport(
            status=partial.status,
            health_score=partial.health_score,
            strategy_stats=partial.strategy_stats,
            dominant_strategy=partial.dominant_strategy,
            dominant_share=partial.dominant_share,
            stale_strategy_ids=partial.stale_strategy_ids,
            drift_max=partial.drift_max,
            window_size=partial.window_size,
            total_decisions=partial.total_decisions,
            window_decisions=partial.window_decisions,
            ledger_chain_valid=partial.ledger_chain_valid,
            report_digest=digest,
        )
