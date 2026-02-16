# SPDX-License-Identifier: Apache-2.0
"""Deterministic UTC clock formatting helpers."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now_iso(now: datetime | None = None) -> str:
    """Return UTC RFC3339/Z timestamp.

    Optional ``now`` enables deterministic tests.
    """

    ts = now or datetime.now(timezone.utc)
    return ts.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_iso(now: datetime | None = None) -> str:
    """Backward-compatible alias for :func:`utc_now_iso`."""

    return utc_now_iso(now)


def utc_timestamp_label(now: datetime | None = None) -> str:
    """Return compact UTC timestamp label for file names (YYYYmmddHHMMSS)."""

    ts = now or datetime.now(timezone.utc)
    return ts.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")


__all__ = ["utc_now_iso", "now_iso", "utc_timestamp_label"]
