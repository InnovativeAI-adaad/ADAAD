# SPDX-License-Identifier: Apache-2.0
"""ProposalCaptureEvent and ProposalCaptureLedger — REPLAY-CAPTURE-0.

Every LLM call in the proposal pipeline MUST write a ProposalCaptureEvent to
this ledger before the response is used in downstream scoring.  Replay mode
reads from these entries instead of re-issuing live LLM calls.

Constitutional invariant: REPLAY-CAPTURE-0
    A proposal that references an LLM response with no corresponding capture
    event is a constitutional violation.  The mutation is rejected and an
    incident is written to the governance ledger.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SCHEMA_VERSION = "89.0"
_DORK_EVIDENCE_SCHEMA_VERSION = "dork-evidence-v1"
_DEFAULT_LEDGER_PATH = Path("data/proposal_capture.jsonl")


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProposalCaptureEvent:
    """Immutable record of one LLM proposal call — the replay anchor.

    Fields
    ------
    epoch_id        Epoch that triggered the proposal request.
    cycle_id        Cycle identifier from StrategyInput.
    call_index      Zero-based index of this call within the epoch (allows
                    multiple proposals per epoch to be addressed individually).
    strategy_id     Strategy that produced the prompt.
    prompt_hash     sha256 of ``system_prompt + "\\n" + user_prompt`` —
                    deterministic identifier for the exact prompt sent.
    response_text   Raw text returned by the LLM provider.
    response_hash   sha256(response_text.encode()) — tamper-evident fingerprint.
    provider_ok     Whether the provider call succeeded (ok=True) or fell back.
    error_code      Error code from LLMProviderResult when ok=False; else None.
    ts              ISO-8601 UTC timestamp of the capture event.
    schema_version  Version of this event schema.
    """

    epoch_id:       str
    cycle_id:       str
    call_index:     int
    strategy_id:    str
    prompt_hash:    str
    response_text:  str
    response_hash:  str
    provider_ok:    bool
    error_code:     str | None
    ts:             str
    generated_at:   str
    evidence_schema_version: str
    artifact_id: str
    source_path: str
    provider: str
    schema_version: str = _SCHEMA_VERSION

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        epoch_id:      str,
        cycle_id:      str,
        call_index:    int,
        strategy_id:   str,
        system_prompt: str,
        user_prompt:   str,
        response_text: str,
        provider_ok:   bool,
        error_code:    str | None = None,
    ) -> "ProposalCaptureEvent":
        prompt_hash   = hashlib.sha256(
            (system_prompt + "\n" + user_prompt).encode()
        ).hexdigest()
        response_hash = hashlib.sha256(response_text.encode()).hexdigest()
        generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return cls(
            epoch_id=epoch_id,
            cycle_id=cycle_id,
            call_index=call_index,
            strategy_id=strategy_id,
            prompt_hash=prompt_hash,
            response_text=response_text,
            response_hash=response_hash,
            provider_ok=provider_ok,
            error_code=error_code,
            ts=generated_at,
            generated_at=generated_at,
            evidence_schema_version=_DORK_EVIDENCE_SCHEMA_VERSION,
            artifact_id=str(uuid.uuid4()),
            source_path="provider_adapter",
            provider="llm_provider_client",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

class ProposalCaptureLedger:
    """Append-only JSONL ledger of ProposalCaptureEvent records.

    Thread-safe via a per-instance lock — safe for concurrent epoch workers.

    Usage
    -----
    ::

        ledger = ProposalCaptureLedger()
        event  = ProposalCaptureEvent.build(...)
        ledger.append(event)

        # Replay: find capture for a given cycle+call
        captured = ledger.get(cycle_id="c-001", call_index=0)

    Constitutional compliance
    -------------------------
    REPLAY-CAPTURE-0 — ``append()`` is the enforcement point.  The adapter
    calls this *before* passing the response to downstream scoring.  Any path
    that bypasses this call produces a constitutionally invalid proposal.
    """

    def __init__(
        self,
        ledger_path: Path | None = None,
    ) -> None:
        self._path  = ledger_path or _DEFAULT_LEDGER_PATH
        self._lock  = threading.Lock()
        self._cache: list[ProposalCaptureEvent] = []
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._load_existing()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(self, event: ProposalCaptureEvent) -> None:
        """Append *event* to the ledger.  Must be called before response use."""
        with self._lock:
            line = json.dumps(event.to_dict(), sort_keys=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            self._cache.append(event)
            log.debug(
                "ProposalCaptureLedger: wrote capture cycle=%s call=%d strategy=%s ok=%s",
                event.cycle_id, event.call_index, event.strategy_id, event.provider_ok,
            )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def entries(self) -> list[ProposalCaptureEvent]:
        """Return all captured events (in append order)."""
        with self._lock:
            return list(self._cache)

    def get(
        self,
        *,
        cycle_id:   str,
        call_index: int,
    ) -> ProposalCaptureEvent | None:
        """Return the capture event for *cycle_id* + *call_index*, or None."""
        with self._lock:
            for e in reversed(self._cache):
                if e.cycle_id == cycle_id and e.call_index == call_index:
                    return e
        return None

    def entries_for_epoch(self, epoch_id: str) -> list[ProposalCaptureEvent]:
        with self._lock:
            return [e for e in self._cache if e.epoch_id == epoch_id]

    def verify_response_hash(
        self,
        *,
        cycle_id:   str,
        call_index: int,
        response_text: str,
    ) -> bool:
        """Return True iff the stored response_hash matches *response_text*."""
        event = self.get(cycle_id=cycle_id, call_index=call_index)
        if event is None:
            return False
        expected = hashlib.sha256(response_text.encode()).hexdigest()
        return event.response_hash == expected

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        try:
            with self._path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        self._cache.append(
                            ProposalCaptureEvent(
                                epoch_id=d.get("epoch_id", ""),
                                cycle_id=d.get("cycle_id", ""),
                                call_index=d.get("call_index", 0),
                                strategy_id=d.get("strategy_id", ""),
                                prompt_hash=d.get("prompt_hash", ""),
                                response_text=d.get("response_text", ""),
                                response_hash=d.get("response_hash", ""),
                                provider_ok=bool(d.get("provider_ok", False)),
                                error_code=d.get("error_code"),
                                ts=d.get("ts", ""),
                                generated_at=d.get("generated_at", d.get("ts", "")),
                                evidence_schema_version=d.get("evidence_schema_version", ""),
                                artifact_id=d.get("artifact_id", ""),
                                source_path=d.get("source_path", "provider_adapter"),
                                provider=d.get("provider", "llm_provider_client"),
                                schema_version=d.get("schema_version", _SCHEMA_VERSION),
                            )
                        )
                    except Exception as exc:
                        log.warning("ProposalCaptureLedger: skipping malformed entry: %s", exc)
        except OSError as exc:
            log.warning("ProposalCaptureLedger: could not load %s: %s", self._path, exc)


# ---------------------------------------------------------------------------
# Module-level singleton (optional convenience — callers may inject directly)
# ---------------------------------------------------------------------------

_default_ledger: ProposalCaptureLedger | None = None
_singleton_lock = threading.Lock()


def get_default_ledger() -> ProposalCaptureLedger:
    """Return the process-wide default ProposalCaptureLedger (lazy init)."""
    global _default_ledger
    if _default_ledger is None:
        with _singleton_lock:
            if _default_ledger is None:
                _default_ledger = ProposalCaptureLedger()
    return _default_ledger
