# runtime/innovations30/dork_living_fleet.py
# Phase 132 · INNOV-41 · DORK Living Fleet
# Constitutional invariants: DORK-FLEET-0, DORK-CMD-0, DORK-STATE-0,
#                            DORK-PROV-0, DORK-CTX-0, DORK-OUTPUT-0
# SPDX-License-Identifier: Apache-2.0

"""
DORK Living Fleet — Phase 132 Innovation (INNOV-41)

A governed, multi-engine orchestrator that routes DORK queries through a
living fleet of LLM provider backends, slash-command resolvers, and
conversation ledger engines — all under constitutional invariant enforcement.

World-first claim: Constitutional Fail-Closed provider fleet with
hash-chained conversation ledger and Jaccard-taxonomy intent routing,
operating under a single HUMAN-0 governance authority.

DORK-FLEET-0 (Hard):
  DORKLivingFleet MUST NOT promote any mutation without a successful
  DorkCommandResolver pre-validation pass. Fleet health status MUST be
  queryable at all times — a fleet with no healthy providers is
  constitutionally BLOCKED.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Internal DORK modules
from dorkllm.state import (
    ConversationLedger,
    ConversationLedgerViolation,
    ProviderHealthRegistry,
    ProviderStatus,
)
from dorkllm.context import classify_query, get_taxonomy_hints
from runtime.dork_cmd_resolver import DorkCommandResolver, CommandError, ManifestLoadError


# ── INNOV-41 Metadata ─────────────────────────────────────────────────────────
INNOV_ID = "INNOV-41"
PHASE = 132
VERSION = "9.64.0"
WORLD_FIRST = (
    "Constitutional Fail-Closed provider fleet with hash-chained conversation "
    "ledger and Jaccard-taxonomy intent routing under HUMAN-0 governance authority"
)


# ── Fleet Exceptions ──────────────────────────────────────────────────────────
class FleetBlockedError(RuntimeError):
    """DORK-FLEET-0: raised when fleet has no healthy providers."""


class FleetMutationBlockedError(RuntimeError):
    """DORK-FLEET-0: raised when mutation promotion attempted without cmd resolver pass."""


# ── Engine Types ──────────────────────────────────────────────────────────────
@dataclass
class FleetEngine:
    """A single provider engine in the DORK Living Fleet."""
    name: str
    provider_type: str          # "ollama" | "remote" | "stub"
    url: str
    model: str
    priority: int
    timeout_seconds: float = 30.0
    _healthy: bool = field(default=True, repr=False)

    def probe(self) -> ProviderStatus:
        """Probe this engine's health. Returns a ProviderStatus."""
        import urllib.request
        t0 = time.monotonic()
        try:
            req = urllib.request.Request(
                f"{self.url}/api/tags",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                resp.read()
            latency = (time.monotonic() - t0) * 1000
            self._healthy = True
            return ProviderStatus(self.name, healthy=True, latency_ms=latency)
        except Exception as exc:
            latency = (time.monotonic() - t0) * 1000
            self._healthy = False
            return ProviderStatus(self.name, healthy=False, latency_ms=latency, error=str(exc))

    def is_healthy(self) -> bool:
        return self._healthy


# ── Fleet Router ──────────────────────────────────────────────────────────────
class FleetRouter:
    """
    Routes queries to the highest-priority healthy engine.
    DORK-FLEET-0: if no healthy engines exist, raises FleetBlockedError.
    """

    def __init__(self, engines: list[FleetEngine]) -> None:
        self._engines = sorted(engines, key=lambda e: e.priority)

    def select(self) -> FleetEngine:
        """Return the highest-priority healthy engine or raise FleetBlockedError."""
        for engine in self._engines:
            if engine.is_healthy():
                return engine
        raise FleetBlockedError(
            "DORK-FLEET-0: Fleet BLOCKED — no healthy providers available. "
            "Query fleet_status() and restore at least one provider before proceeding."
        )

    def all_engines(self) -> list[FleetEngine]:
        return list(self._engines)

    def healthy_count(self) -> int:
        return sum(1 for e in self._engines if e.is_healthy())


# ── Fleet Dispatch Result ─────────────────────────────────────────────────────
@dataclass
class FleetDispatchResult:
    query: str
    intent: str
    intent_confidence: float
    engine_used: str
    response: str
    conversation_ledger_seq: int
    fleet_health_snapshot: dict
    duration_ms: float
    status: str                 # "ok" | "blocked" | "error"
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "intent": self.intent,
            "intent_confidence": self.intent_confidence,
            "engine_used": self.engine_used,
            "response": self.response,
            "conversation_ledger_seq": self.conversation_ledger_seq,
            "fleet_health_snapshot": self.fleet_health_snapshot,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status,
            "error": self.error,
        }


# ── DORK Living Fleet ─────────────────────────────────────────────────────────
class DORKLivingFleet:
    """
    INNOV-41: DORK Living Fleet Orchestrator.

    Integrates four engines under six Hard constitutional invariants:
      1. SlashCommandEngine  — DorkCommandResolver (DORK-CMD-0)
      2. ProviderFleetEngine — FleetRouter + ProviderHealthRegistry (DORK-FLEET-0, DORK-PROV-0)
      3. ConversationEngine  — ConversationLedger (DORK-STATE-0)
      4. IntentEngine        — CONTEXT_KEYWORD_TAXONOMY + Jaccard (DORK-CTX-0)

    All LLM output passes through OPT-005 sanitizer (DORK-OUTPUT-0).
    """

    CONSTITUTIONAL_INVARIANTS = [
        "DORK-FLEET-0", "DORK-CMD-0", "DORK-STATE-0",
        "DORK-PROV-0",  "DORK-CTX-0", "DORK-OUTPUT-0",
    ]

    def __init__(
        self,
        engines: list[FleetEngine] | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        # Engine 1: Slash command resolver
        try:
            self._cmd_resolver = DorkCommandResolver(manifest_path=manifest_path)
        except ManifestLoadError:
            self._cmd_resolver = None

        # Engine 2: Provider fleet
        self._engines = engines or self._default_engines()
        self._router = FleetRouter(self._engines)
        self._provider_registry = ProviderHealthRegistry()

        # Engine 3: Conversation ledger
        self._conversation_ledger = ConversationLedger()

        # Fleet-level chain ledger for dispatch events
        self._dispatch_ledger: list[dict] = []
        self._dispatch_prev_hash = "0" * 64

        # Initial health probe
        self._probe_all()

    # ── Default engines from provider_config.json ─────────────────────────────
    @staticmethod
    def _default_engines() -> list[FleetEngine]:
        cfg_path = Path(__file__).parent.parent.parent / "data" / "dork" / "provider_config.json"
        try:
            cfg = json.loads(cfg_path.read_text())
            engines = []
            for p in cfg.get("providers", []):
                url = p.get("url") or os.getenv(p.get("url_env", ""), "http://localhost:11434")
                model = p.get("model") or os.getenv(p.get("model_env", ""), "dork")
                engines.append(FleetEngine(
                    name=p["name"],
                    provider_type=p.get("type", "ollama"),
                    url=url,
                    model=model,
                    priority=p.get("priority", 99),
                    timeout_seconds=p.get("timeout_seconds", 30),
                ))
            return engines
        except Exception:
            return [FleetEngine(
                name="ollama_local",
                provider_type="ollama",
                url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
                model=os.getenv("OLLAMA_MODEL", "dork"),
                priority=1,
            )]

    # ── Health probe ──────────────────────────────────────────────────────────
    def _probe_all(self) -> None:
        """Probe all engines and record results in ProviderHealthRegistry."""
        for engine in self._engines:
            status = engine.probe()
            self._provider_registry.record(status)

    def probe_engine(self, name: str) -> ProviderStatus | None:
        """Probe a specific engine by name and record result."""
        for engine in self._engines:
            if engine.name == name:
                status = engine.probe()
                self._provider_registry.record(status)
                return status
        return None

    # ── Fleet status (DORK-FLEET-0) ───────────────────────────────────────────
    def fleet_status(self) -> dict:
        """
        Return full fleet health snapshot.
        DORK-FLEET-0: always queryable; blocked=True when no healthy providers.
        """
        provider_summary = self._provider_registry.summary()
        healthy_count = self._router.healthy_count()
        blocked = healthy_count == 0
        return {
            "innov_id": INNOV_ID,
            "phase": PHASE,
            "version": VERSION,
            "constitutional_invariants": self.CONSTITUTIONAL_INVARIANTS,
            "blocked": blocked,
            "healthy_provider_count": healthy_count,
            "total_provider_count": len(self._engines),
            "providers": provider_summary,
            "conversation_ledger_entries": len(self._conversation_ledger),
            "dispatch_ledger_entries": len(self._dispatch_ledger),
            "cmd_resolver_loaded": self._cmd_resolver is not None,
            "cmd_resolver_commands": (
                len(self._cmd_resolver.known_commands()) if self._cmd_resolver else 0
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ── Slash command dispatch (DORK-CMD-0) ───────────────────────────────────
    def dispatch_slash(self, raw_input: str) -> dict:
        """
        Validate and dispatch a slash command via DorkCommandResolver.
        DORK-CMD-0: unknown commands are rejected with CommandError — never forwarded.
        """
        if self._cmd_resolver is None:
            return {
                "status": "error",
                "error": "DORK-CMD-0: CommandResolver not loaded — manifest missing.",
                "slash": raw_input,
            }
        result = self._cmd_resolver.resolve(raw_input)
        self._ledger_dispatch_event("slash_command", raw_input, result["status"])
        return result

    # ── Natural language query dispatch ───────────────────────────────────────
    def query(self, text: str) -> FleetDispatchResult:
        """
        Route a natural-language DORK query through the full pipeline:
          Intent → Provider selection → LLM → OPT-005 sanitize → Ledger
        """
        t0 = time.monotonic()

        # Engine 4: Intent classification (DORK-CTX-0)
        intent_cat, intent_conf = classify_query(text)

        # Engine 2: Provider selection (DORK-FLEET-0)
        try:
            engine = self._router.select()
        except FleetBlockedError as exc:
            duration = (time.monotonic() - t0) * 1000
            return FleetDispatchResult(
                query=text,
                intent=intent_cat,
                intent_confidence=intent_conf,
                engine_used="none",
                response="",
                conversation_ledger_seq=-1,
                fleet_health_snapshot=self.fleet_status(),
                duration_ms=duration,
                status="blocked",
                error=str(exc),
            )

        # Engine 1: Check if slash command
        if text.strip().startswith("/dork:"):
            slash_result = self.dispatch_slash(text.strip())
            response = (
                f"[DORK-CMD] Resolved: {slash_result.get('intent')} "
                f"— {slash_result.get('description', '')}"
                if slash_result["status"] == "ok"
                else f"[DORK-CMD-0 VIOLATION] {slash_result['error']}"
            )
        else:
            # Standard LLM dispatch (stub — actual Ollama call in intelligence.py)
            response = (
                f"[DORK·{engine.name}] Query routed to {engine.model} "
                f"via {engine.url} (intent={intent_cat}, conf={intent_conf:.3f}). "
                f"Connect Ollama to receive full response."
            )

        # Engine 3: Conversation ledger (DORK-STATE-0)
        try:
            user_entry = self._conversation_ledger.append("user", text)
            asst_entry = self._conversation_ledger.append("assistant", response)
            ledger_seq = asst_entry["seq"]
        except ConversationLedgerViolation as exc:
            ledger_seq = -1

        # OPT-005 sanitize (DORK-OUTPUT-0)
        from dorkllm.intelligence import opt_005_sanitize_output
        response, _ = opt_005_sanitize_output(response, text)

        duration = (time.monotonic() - t0) * 1000
        self._ledger_dispatch_event("nlq", text[:80], "ok")

        return FleetDispatchResult(
            query=text,
            intent=intent_cat,
            intent_confidence=intent_conf,
            engine_used=engine.name,
            response=response,
            conversation_ledger_seq=ledger_seq,
            fleet_health_snapshot=self.fleet_status(),
            duration_ms=duration,
            status="ok",
        )

    # ── Mutation promotion guard (DORK-FLEET-0) ───────────────────────────────
    def assert_promotion_allowed(self, slash_validation_result: dict) -> None:
        """
        DORK-FLEET-0: Raise FleetMutationBlockedError if promotion attempted
        without a successful CommandResolver validation pass.
        """
        if slash_validation_result.get("status") != "ok":
            raise FleetMutationBlockedError(
                f"DORK-FLEET-0: Mutation promotion BLOCKED — "
                f"CommandResolver pass required. "
                f"Error: {slash_validation_result.get('error')}"
            )

    # ── Dispatch chain ledger ─────────────────────────────────────────────────
    def _ledger_dispatch_event(self, event_type: str, payload: str, status: str) -> None:
        entry_data = {
            "seq": len(self._dispatch_ledger),
            "event_type": event_type,
            "payload_digest": hashlib.sha256(payload.encode()).hexdigest()[:24],
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prev_hash": self._dispatch_prev_hash,
        }
        combined = json.dumps(entry_data, sort_keys=True)
        entry_data["entry_hash"] = hashlib.sha256(combined.encode()).hexdigest()
        self._dispatch_ledger.append(entry_data)
        self._dispatch_prev_hash = entry_data["entry_hash"]

    def dispatch_ledger_tail(self, n: int = 10) -> list[dict]:
        return self._dispatch_ledger[-n:]

    def verify_dispatch_ledger(self) -> tuple[bool, str]:
        """Verify dispatch chain integrity."""
        prev = "0" * 64
        for e in self._dispatch_ledger:
            if e["prev_hash"] != prev:
                return False, f"Chain break at seq={e['seq']}"
            prev = e["entry_hash"]
        return True, "chain_valid"

    # ── Conversation ledger accessor ──────────────────────────────────────────
    def conversation_ledger_tail(self, n: int = 5) -> list[dict]:
        return self._conversation_ledger.tail(n)

    def verify_conversation_ledger(self) -> tuple[bool, str]:
        return self._conversation_ledger.verify()
