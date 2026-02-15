# SPDX-License-Identifier: Apache-2.0

"""Canonical governance event taxonomy and normalization helpers."""

from __future__ import annotations

from typing import Any, Mapping

EVENT_TYPE_CONSTITUTION_ESCALATION = "constitution_escalation"
EVENT_TYPE_REPLAY_FAILURE = "replay_failure"
EVENT_TYPE_REPLAY_DIVERGENCE = "replay_divergence"
EVENT_TYPE_OPERATOR_OVERRIDE = "operator_override"

LEGACY_EVENT_TYPE_FALLBACKS: dict[str, str] = {
    "constitution_escalated": EVENT_TYPE_CONSTITUTION_ESCALATION,
    "manual_override": EVENT_TYPE_OPERATOR_OVERRIDE,
    "operator_manual_override": EVENT_TYPE_OPERATOR_OVERRIDE,
    "replay_check_failed": EVENT_TYPE_REPLAY_FAILURE,
    "replay_verification_failed": EVENT_TYPE_REPLAY_FAILURE,
    "replay_divergence_detected": EVENT_TYPE_REPLAY_DIVERGENCE,
}


CANONICAL_EVENT_TYPES = {
    EVENT_TYPE_CONSTITUTION_ESCALATION,
    EVENT_TYPE_REPLAY_FAILURE,
    EVENT_TYPE_REPLAY_DIVERGENCE,
    EVENT_TYPE_OPERATOR_OVERRIDE,
}


def normalize_event_type(entry: Mapping[str, Any]) -> str:
    """Resolve a normalized event type from mixed legacy and canonical fields."""

    event_type = str(entry.get("event_type", "")).strip().lower()
    if event_type in CANONICAL_EVENT_TYPES:
        return event_type
    if event_type in LEGACY_EVENT_TYPE_FALLBACKS:
        return LEGACY_EVENT_TYPE_FALLBACKS[event_type]

    event_name = str(entry.get("event", "")).strip().lower()
    if event_name in LEGACY_EVENT_TYPE_FALLBACKS:
        return LEGACY_EVENT_TYPE_FALLBACKS[event_name]

    return event_name
