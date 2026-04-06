# SPDX-License-Identifier: Apache-2.0
"""Deterministic append-only Dork intent execution stream."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from runtime.timeutils import now_iso

DEFAULT_DORK_EVENT_STREAM_PATH = Path("data/dork_event_stream.jsonl")


class DorkEventStream:
    """Append intent execution events to a JSONL stream."""

    def __init__(self, path: Path = DEFAULT_DORK_EVENT_STREAM_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _digest(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(canonical.encode("utf-8")).hexdigest()

    def append(
        self,
        *,
        intent: str,
        query: str,
        bundle_digest: str,
        marker: dict[str, bool],
        evidence_refs: list[str],
        trust_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "event_type": "dork_intent_executed.v1",
            "intent": intent,
            "query": query,
            "bundle_digest": bundle_digest,
            "marker": marker,
            "evidence_refs": list(evidence_refs),
            "trust_metadata": dict(trust_metadata or {}),
            "ts": now_iso(),
        }
        event["event_digest"] = self._digest(event)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        return event

    def append_snapshot_interpretation(
        self,
        *,
        query: str,
        before_snapshot: dict[str, Any],
        after_snapshot: dict[str, Any],
        interpretation: dict[str, Any],
        bundle_digest: str,
    ) -> dict[str, Any]:
        event = {
            "event_type": "dork_snapshot_interpreted.v1",
            "query": query,
            "bundle_digest": bundle_digest,
            "before_snapshot": before_snapshot,
            "after_snapshot": after_snapshot,
            "interpretation": interpretation,
            "ts": now_iso(),
        }
        event["event_digest"] = self._digest(event)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        return event
