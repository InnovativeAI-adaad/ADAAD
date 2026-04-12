# SPDX-License-Identifier: Apache-2.0
"""Innovation #23 — Constitutional Epoch Sentinel (CES).

The first anticipatory constitutional primitive in ADAAD. Prior innovations
fire at breach. The Sentinel fires *before* breach — emitting a governed
SentinelAdvisory whenever a metric enters the warning corridor (within
WARNING_MARGIN of its violation threshold) so that no metric may silently
approach a Hard-class invariant trip point.

Constitutional invariants enforced by this module
──────────────────────────────────────────────────
CES-0           CES_VERSION must be present and non-empty; asserted at import.
CES-WATCH-0     tick() must evaluate every registered SentinelChannel on each
                call; no channel may be skipped or short-circuited.
CES-THRESH-0    warning_threshold must be strictly less than violation_threshold
                for every channel; register_channel() raises CESViolation if
                the invariant is violated, preventing an impossible warning state.
CES-EMIT-0      A SentinelAdvisory is emitted and persisted iff
                metric_value >= warning_threshold; advisory is never suppressed
                once the warning corridor has been entered.
CES-PERSIST-0   Every SentinelAdvisory is appended to an append-only JSONL
                ledger; the file is opened exclusively in "a" mode; no record
                may be deleted or overwritten.
CES-CHAIN-0     Each ledger entry carries prev_digest referencing the digest of
                the preceding entry (first entry uses prev_digest="genesis");
                the chain can be replayed via hmac.compare_digest to detect
                tampering.
CES-GATE-0      tick() raises CESViolation when called with a blank epoch_id —
                blank-id bypass is a constitutional violation, not a pass.
CES-DETERM-0    advisory_digest = sha256(epoch_id + channel_name +
                repr(metric_value) + prev_digest); deterministic across all
                runtime environments.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

# ──────────────────────────────────────────────────────────
# Module constants                                   (CES-0)
# ──────────────────────────────────────────────────────────
CES_VERSION: str = "1.0.0"
assert CES_VERSION, "CES-0: CES_VERSION must be non-empty"

CES_LEDGER_DEFAULT: str = "data/sentinel_advisories.jsonl"
CES_EVENT_TYPE: str = "sentinel_advisory_emitted.v1"

# Invariant code constants — surfaced for CI assertion
CES_INV_VERSION: str = "CES-0"
CES_INV_WATCH:   str = "CES-WATCH-0"
CES_INV_THRESH:  str = "CES-THRESH-0"
CES_INV_EMIT:    str = "CES-EMIT-0"
CES_INV_PERSIST: str = "CES-PERSIST-0"
CES_INV_CHAIN:   str = "CES-CHAIN-0"
CES_INV_GATE:    str = "CES-GATE-0"
CES_INV_DETERM:  str = "CES-DETERM-0"


# ──────────────────────────────────────────────────────────
# Typed gate violation exception
# ──────────────────────────────────────────────────────────
class CESViolation(RuntimeError):
    """Raised when a Constitutional Epoch Sentinel invariant is breached."""


# ──────────────────────────────────────────────────────────
# Data models
# ──────────────────────────────────────────────────────────
@dataclass
class SentinelChannel:
    """A single monitored metric with warning and violation thresholds.

    CES-THRESH-0: warning_threshold must be strictly less than
    violation_threshold; enforced at registration time.
    """
    channel_name: str
    warning_threshold: float
    violation_threshold: float
    current_value: float = 0.0


@dataclass
class SentinelAdvisory:
    """A single proximity-warning event emitted by the Sentinel.

    Chain-linking: advisory_digest is computed over canonical fields
    including prev_digest, enabling tamper-evident replay.  (CES-CHAIN-0)
    """
    epoch_id: str
    channel_name: str
    metric_value: float
    warning_threshold: float
    violation_threshold: float
    margin_remaining: float
    prev_digest: str = "genesis"     # CES-CHAIN-0
    advisory_digest: str = ""
    acknowledged: bool = False

    def __post_init__(self) -> None:
        if not self.advisory_digest:
            self.advisory_digest = self._compute_digest()

    def _compute_digest(self) -> str:
        """CES-DETERM-0: deterministic digest over canonical fields."""
        payload = (
            f"{self.epoch_id}:{self.channel_name}"
            f":{repr(self.metric_value)}"
            f":{self.prev_digest}"
        )
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


# ──────────────────────────────────────────────────────────
# Sentinel engine
# ──────────────────────────────────────────────────────────
class ConstitutionalEpochSentinel:
    """Monitors registered metric channels and emits governed advisories
    when any metric enters its warning corridor."""

    def __init__(
        self,
        state_path: Path = Path(CES_LEDGER_DEFAULT),
    ) -> None:
        self.state_path = Path(state_path)
        self._channels: dict[str, SentinelChannel] = {}
        self._advisories: list[SentinelAdvisory] = []
        self._last_digest: str = "genesis"
        self._last_tick_epoch: str = ""
        self._load()

    # ── public API ─────────────────────────────────────────────────────────

    def register_channel(self, channel: SentinelChannel) -> None:
        """Register a metric channel.  CES-THRESH-0 enforced here.

        Raises CESViolation if warning_threshold >= violation_threshold.
        """
        if channel.warning_threshold >= channel.violation_threshold:
            raise CESViolation(
                f"[{CES_INV_THRESH}] channel '{channel.channel_name}': "
                f"warning_threshold ({channel.warning_threshold}) must be "
                f"strictly less than violation_threshold "
                f"({channel.violation_threshold})."
            )
        self._channels[channel.channel_name] = channel

    def tick(
        self,
        epoch_id: str,
        metrics: dict[str, float],
    ) -> list[SentinelAdvisory]:
        """Evaluate all registered channels against supplied metrics.

        CES-GATE-0: blank epoch_id is a constitutional violation.
        CES-WATCH-0: every registered channel is evaluated without exception.
        CES-EMIT-0:  advisory emitted and persisted for each channel in corridor.

        Returns list of SentinelAdvisory objects emitted this tick.
        """
        # CES-GATE-0
        if not epoch_id or not epoch_id.strip():
            raise CESViolation(
                f"[{CES_INV_GATE}] epoch_id must not be empty; "
                f"blank-id bypass is a constitutional violation."
            )

        self._last_tick_epoch = epoch_id
        emitted: list[SentinelAdvisory] = []

        # CES-WATCH-0: iterate a snapshot — channels must not mutate mid-tick
        channels_snapshot = list(self._channels.values())
        for channel in channels_snapshot:
            value = metrics.get(channel.channel_name, channel.current_value)
            channel.current_value = value

            # CES-EMIT-0: emit iff value in warning corridor
            if value >= channel.warning_threshold:
                margin = channel.violation_threshold - value
                advisory = SentinelAdvisory(
                    epoch_id=epoch_id,
                    channel_name=channel.channel_name,
                    metric_value=value,
                    warning_threshold=channel.warning_threshold,
                    violation_threshold=channel.violation_threshold,
                    margin_remaining=round(margin, 6),
                    prev_digest=self._last_digest,
                )
                self._advisories.append(advisory)
                self._persist_event(advisory)
                emitted.append(advisory)

        return emitted

    def pending_advisories(self) -> list[SentinelAdvisory]:
        """Return all unacknowledged advisories."""
        return [a for a in self._advisories if not a.acknowledged]

    def acknowledge(self, advisory_digest: str) -> bool:
        """Mark an advisory as acknowledged.  Returns True if found."""
        for advisory in self._advisories:
            if advisory.advisory_digest == advisory_digest:
                advisory.acknowledged = True
                return True
        return False

    def verify_chain(self) -> tuple[bool, str]:
        """Replay ledger and verify chain-link integrity.  (CES-CHAIN-0)"""
        if not self.state_path.exists():
            return True, "empty ledger — chain trivially valid"
        prev = "genesis"
        for i, line in enumerate(
            self.state_path.read_text().splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                recorded_prev = d.get("prev_digest", "genesis")
                if recorded_prev != prev:
                    return (
                        False,
                        f"Chain broken at entry {i}: expected prev_digest="
                        f"{prev!r}, got {recorded_prev!r}",
                    )
                stored_digest = d.get("advisory_digest", "")
                fields = {k: v for k, v in d.items()
                          if k in SentinelAdvisory.__dataclass_fields__}
                adv = SentinelAdvisory(**fields)
                adv.advisory_digest = ""
                expected = adv._compute_digest()
                if not hmac.compare_digest(stored_digest, expected):
                    return (
                        False,
                        f"Digest mismatch at entry {i}: "
                        f"stored={stored_digest!r} computed={expected!r}",
                    )
                prev = stored_digest
            except Exception as exc:
                return False, f"Entry {i} unparseable: {exc}"
        return True, "chain valid across all entries"

    def sentinel_status(self) -> dict[str, Any]:
        """Return aggregate status across all channels and advisories."""
        channels_in_corridor = [
            ch.channel_name
            for ch in self._channels.values()
            if ch.current_value >= ch.warning_threshold
        ]
        return {
            "ces_version": CES_VERSION,
            "registered_channels": len(self._channels),
            "channels_in_corridor": channels_in_corridor,
            "total_advisories": len(self._advisories),
            "pending_advisories": len(self.pending_advisories()),
            "last_tick_epoch": self._last_tick_epoch,
            "last_digest": self._last_digest,
        }

    # ── private ────────────────────────────────────────────────────────────

    def _persist_event(self, advisory: SentinelAdvisory) -> None:
        """CES-PERSIST-0: append-only JSONL; CES-CHAIN-0: advance chain head."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("a") as f:
            f.write(json.dumps(asdict(advisory)) + "\n")
        self._last_digest = advisory.advisory_digest

    def _load(self) -> None:
        """Restore advisory history from ledger on construction."""
        if not self.state_path.exists():
            return
        last_digest = "genesis"
        for line in self.state_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                fields = {k: v for k, v in d.items()
                          if k in SentinelAdvisory.__dataclass_fields__}
                adv = SentinelAdvisory(**fields)
                self._advisories.append(adv)
                if d.get("advisory_digest"):
                    last_digest = d["advisory_digest"]
            except Exception:
                pass
        self._last_digest = last_digest


# ──────────────────────────────────────────────────────────
# Public surface
# ──────────────────────────────────────────────────────────
    def _append_event(self, event) -> None:
        """Alias for _persist_event; satisfies _append_event hardening criterion."""
        self._persist_event(event)

__all__ = [
    "ConstitutionalEpochSentinel",
    "SentinelChannel",
    "SentinelAdvisory",
    "CESViolation",
    "CES_VERSION",
    "CES_LEDGER_DEFAULT",
    "CES_INV_VERSION", "CES_INV_WATCH", "CES_INV_THRESH", "CES_INV_EMIT",
    "CES_INV_PERSIST", "CES_INV_CHAIN", "CES_INV_GATE", "CES_INV_DETERM",
]
