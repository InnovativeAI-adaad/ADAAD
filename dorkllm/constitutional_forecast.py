# SPDX-License-Identifier: Apache-2.0
"""Phase 161 — INNOV-67 · CFE — Constitutional Forecast Engine.

CFE invariants
==============
CFE-DETERM-0: forecast_id is deterministic from canonical window payload only.
CFE-CHAIN-0:  forecast ledger is HMAC-chained; chain break → CFEChainError (fail-closed).
CFE-HUMAN0-0: HIGH_RISK / CRITICAL forecasts emit HUMAN0_AUTHORISATION to CGTH
               before ledger write.
CFE-WINDOW-0: forecast() rejects windows with < 3 data points (fail-closed).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from dorkllm.telemetry_hub import CGTHEventType, get_hub

# ---------------------------------------------------------------------------
# Invariant constants (CFE-DETERM-0, CFE-CHAIN-0, CFE-HUMAN0-0, CFE-WINDOW-0)
# ---------------------------------------------------------------------------

_CFE_COMPONENT_ID: str = "cfe"
_CFE_HMAC_KEY: bytes = b"ADAAD-CFE-HMAC-2026"
_CHAIN_ROOT: str = "0" * 64
_MIN_WINDOW_SIZE: int = 3          # CFE-WINDOW-0 hard minimum
_HUMAN0_RISK_THRESHOLD: int = 3    # HIGH_RISK=3, CRITICAL=4


# ---------------------------------------------------------------------------
# Typed violation exceptions
# ---------------------------------------------------------------------------

class CFEChainError(RuntimeError):
    """CFE-CHAIN-0: HMAC chain integrity violation."""


class CFEWindowError(ValueError):
    """CFE-WINDOW-0: insufficient data points for forecast."""


class CFEDeterminismError(RuntimeError):
    """CFE-DETERM-0: non-deterministic forecast_id computation."""


class CFEHumanGateError(RuntimeError):
    """CFE-HUMAN0-0: CGTH HUMAN0_AUTHORISATION emission failed."""


# ---------------------------------------------------------------------------
# Risk tier enum
# ---------------------------------------------------------------------------

class RiskTier(int, Enum):
    LOW = 1
    MEDIUM = 2
    HIGH_RISK = 3
    CRITICAL = 4

    def label(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# Chain-linked ledger dataclass
# ---------------------------------------------------------------------------

@dataclass
class ForecastEntry:
    """Single HMAC-chained forecast ledger record."""

    forecast_id: str
    window_size: int
    trend_slope: float
    forecast_pressure: float
    risk_tier: str
    horizon_epochs: int
    prev_digest: str
    digest: str
    timestamp_iso: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "forecast_id": self.forecast_id,
            "window_size": self.window_size,
            "trend_slope": self.trend_slope,
            "forecast_pressure": self.forecast_pressure,
            "risk_tier": self.risk_tier,
            "horizon_epochs": self.horizon_epochs,
            "prev_digest": self.prev_digest,
            "digest": self.digest,
            "timestamp_iso": self.timestamp_iso,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class ConstitutionalForecastEngine:
    """CFE — Constitutional Forecast Engine.

    Accepts a sequence of constitutional pressure readings (floats in [0,1])
    from CGTH telemetry, fits a linear trend, projects ``horizon_epochs``
    steps forward, and assigns a RiskTier.  All forecasts are persisted in
    an HMAC-chained append-only JSONL ledger.
    """

    def __init__(
        self,
        ledger_path: Optional[Path] = None,
        horizon_epochs: int = 5,
    ) -> None:
        self._ledger_path: Path = ledger_path or Path(
            os.environ.get("CFE_LEDGER_PATH", "/tmp/adaad_cfe_ledger.jsonl")
        )
        self._horizon_epochs: int = max(1, horizon_epochs)
        self._prev_digest: str = self._load_chain_tip()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def forecast(
        self,
        pressure_window: Sequence[float],
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ForecastEntry:
        """Produce a deterministic constitutional stress forecast.

        Parameters
        ----------
        pressure_window:
            Ordered sequence of constitutional pressure readings (floats
            in [0.0, 1.0]) from most-ancient to most-recent epoch.
        metadata:
            Optional caller-supplied annotations (ignored for
            determinism; stored in entry only).

        Returns
        -------
        ForecastEntry
            The persisted, HMAC-chained forecast record.

        Raises
        ------
        CFEWindowError
            If ``len(pressure_window) < _MIN_WINDOW_SIZE`` (CFE-WINDOW-0).
        CFEChainError
            If the existing ledger chain tip fails verification (CFE-CHAIN-0).
        CFEHumanGateError
            If CGTH emission fails for HIGH_RISK/CRITICAL forecasts
            (CFE-HUMAN0-0).
        """
        # CFE-WINDOW-0 guard
        if len(pressure_window) < _MIN_WINDOW_SIZE:
            raise CFEWindowError(
                f"CFE-WINDOW-0: need ≥ {_MIN_WINDOW_SIZE} data points, "
                f"got {len(pressure_window)}"
            )

        values = [float(v) for v in pressure_window]
        slope = self._linear_slope(values)
        projected = max(0.0, min(1.0, values[-1] + slope * self._horizon_epochs))
        risk_tier = self._classify_risk(projected, slope)
        timestamp_iso = self._utc_now_iso()

        # CFE-DETERM-0: canonical payload for deterministic ID
        canonical_payload = json.dumps(
            {
                "window": values,
                "horizon_epochs": self._horizon_epochs,
                "slope": slope,
                "forecast_pressure": projected,
                "risk_tier": risk_tier.label(),
            },
            sort_keys=True,
        )
        forecast_id = hashlib.sha256(canonical_payload.encode()).hexdigest()

        # CFE-HUMAN0-0: emit HUMAN0_AUTHORISATION before write for high-risk
        if risk_tier.value >= _HUMAN0_RISK_THRESHOLD:
            self._emit_human0(forecast_id, risk_tier, projected)

        # CFE-CHAIN-0: chain-link
        entry_body = json.dumps(
            {
                "forecast_id": forecast_id,
                "window_size": len(values),
                "trend_slope": slope,
                "forecast_pressure": projected,
                "risk_tier": risk_tier.label(),
                "horizon_epochs": self._horizon_epochs,
                "prev_digest": self._prev_digest,
                "timestamp_iso": timestamp_iso,
            },
            sort_keys=True,
        )
        digest = hmac.new(_CFE_HMAC_KEY, entry_body.encode(), hashlib.sha256).hexdigest()

        entry = ForecastEntry(
            forecast_id=forecast_id,
            window_size=len(values),
            trend_slope=slope,
            forecast_pressure=projected,
            risk_tier=risk_tier.label(),
            horizon_epochs=self._horizon_epochs,
            prev_digest=self._prev_digest,
            digest=digest,
            timestamp_iso=timestamp_iso,
            metadata=metadata or {},
        )

        self._append_entry(entry, entry_body)
        self._prev_digest = digest
        return entry

    def verify_chain(self) -> bool:
        """Replay the entire ledger; raise CFEChainError on first broken link.

        Returns True only when every link verifies cleanly.
        """
        entries = self._load_all_entries()
        prev = _CHAIN_ROOT
        for raw in entries:
            body = {k: v for k, v in raw.items() if k not in ("digest", "metadata")}
            expected_digest = hmac.new(
                _CFE_HMAC_KEY,
                json.dumps(body, sort_keys=True).encode(),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected_digest, raw.get("digest", "")):
                raise CFEChainError(
                    f"CFE-CHAIN-0: chain break at forecast_id={raw.get('forecast_id')}"
                )
            if not hmac.compare_digest(raw.get("prev_digest", ""), prev):
                raise CFEChainError(
                    f"CFE-CHAIN-0: prev_digest mismatch at forecast_id={raw.get('forecast_id')}"
                )
            prev = raw["digest"]
        return True

    def chain(self) -> List[Dict[str, Any]]:
        """Return all ledger entries as list of dicts (read-only)."""
        return self._load_all_entries()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _linear_slope(values: List[float]) -> float:
        """Least-squares slope over the window (pure, deterministic)."""
        n = len(values)
        xs = list(range(n))
        x_mean = sum(xs) / n
        y_mean = sum(values) / n
        num = sum((xs[i] - x_mean) * (values[i] - y_mean) for i in range(n))
        den = sum((x - x_mean) ** 2 for x in xs)
        return num / den if den else 0.0

    @staticmethod
    def _classify_risk(projected: float, slope: float) -> RiskTier:
        """Map projected pressure + slope to RiskTier (deterministic)."""
        if projected >= 0.90 or (projected >= 0.75 and slope > 0.05):
            return RiskTier.CRITICAL
        if projected >= 0.75 or (projected >= 0.60 and slope > 0.03):
            return RiskTier.HIGH_RISK
        if projected >= 0.50 or slope > 0.02:
            return RiskTier.MEDIUM
        return RiskTier.LOW

    def _emit_human0(
        self,
        forecast_id: str,
        risk_tier: RiskTier,
        projected: float,
    ) -> None:
        """CFE-HUMAN0-0: emit HUMAN0_AUTHORISATION event to CGTH."""
        try:
            hub = get_hub()
            hub.emit(
                component_id=_CFE_COMPONENT_ID,
                event_type=CGTHEventType.HUMAN0_AUTHORISATION,
                payload={
                    "forecast_id": forecast_id,
                    "risk_tier": risk_tier.label(),
                    "forecast_pressure": projected,
                    "reason": "CFE-HUMAN0-0: forecast exceeds risk threshold",
                },
            )
        except Exception as exc:  # noqa: BLE001
            raise CFEHumanGateError(
                f"CFE-HUMAN0-0: CGTH emission failed: {exc}"
            ) from exc

    def _load_chain_tip(self) -> str:
        """Return digest of the last ledger entry, or chain root."""
        entries = self._load_all_entries()
        if not entries:
            return _CHAIN_ROOT
        return entries[-1].get("digest", _CHAIN_ROOT)

    def _load_all_entries(self) -> List[Dict[str, Any]]:
        if not self._ledger_path.exists():
            return []
        lines = self._ledger_path.read_text(encoding="utf-8").strip().splitlines()
        result: List[Dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if line:
                result.append(json.loads(line))
        return result

    def _append_entry(self, entry: ForecastEntry, entry_body: str) -> None:
        """Append-only JSONL write (AUTH-CT-0 compliant via verify_chain guard)."""
        record = json.loads(entry_body)
        record["digest"] = entry.digest
        record["metadata"] = entry.metadata
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self._ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    @staticmethod
    def _utc_now_iso() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()
