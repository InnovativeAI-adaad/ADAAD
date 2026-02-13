# SPDX-License-Identifier: Apache-2.0
"""Replay mode enumeration and argument normalization helpers."""

from __future__ import annotations

from enum import Enum


class ReplayMode(str, Enum):
    """Replay verification modes."""

    OFF = "off"
    AUDIT = "audit"
    STRICT = "strict"

    @property
    def fail_closed(self) -> bool:
        """Whether this mode should fail-close on divergence."""
        return self is ReplayMode.STRICT

    @property
    def should_verify(self) -> bool:
        """Whether this mode should run replay verification."""
        return self in (ReplayMode.AUDIT, ReplayMode.STRICT)


_REPLAY_MODE_ALIASES = {
    "": ReplayMode.OFF,
    "off": ReplayMode.OFF,
    "0": ReplayMode.OFF,
    "false": ReplayMode.OFF,
    "no": ReplayMode.OFF,
    "none": ReplayMode.OFF,
    "audit": ReplayMode.AUDIT,
    "full": ReplayMode.AUDIT,
    "on": ReplayMode.AUDIT,
    "1": ReplayMode.AUDIT,
    "true": ReplayMode.AUDIT,
    "yes": ReplayMode.AUDIT,
    "strict": ReplayMode.STRICT,
}


def normalize_replay_mode(value: str | bool | ReplayMode | None) -> ReplayMode:
    """Normalize booleans/strings/enums into ReplayMode."""
    if value is None:
        return ReplayMode.OFF
    if isinstance(value, ReplayMode):
        return value
    if isinstance(value, bool):
        return ReplayMode.AUDIT if value else ReplayMode.OFF
    if isinstance(value, str):
        mode = _REPLAY_MODE_ALIASES.get(value.strip().lower())
        if mode is not None:
            return mode
        raise ValueError(
            f"Invalid replay mode: '{value}'. "
            "Valid modes: off, audit, strict (or legacy: full, on)"
        )
    raise TypeError(f"Invalid replay mode type: {type(value)}. Expected str, bool, ReplayMode, or None")


def parse_replay_args(
    replay_mode: str | bool | ReplayMode | None,
    replay_epoch: str | None = None,
) -> tuple[ReplayMode, str]:
    """Parse CLI replay args into normalized mode and epoch id."""
    mode = normalize_replay_mode(replay_mode)
    epoch_id = (replay_epoch or "").strip()
    return mode, epoch_id


__all__ = ["ReplayMode", "normalize_replay_mode", "parse_replay_args"]
