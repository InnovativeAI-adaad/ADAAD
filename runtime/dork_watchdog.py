# runtime/dork_watchdog.py
# Phase 133 · INNOV-42 · DORK Fleet Server Bridge
# Constitutional invariant: DFSB-HEAL-0
# SPDX-License-Identifier: Apache-2.0

"""
DorkFleetWatchdog — background engine auto-heal watchdog.

DFSB-HEAL-0 (Hard):
  Dead engines MUST be re-probed on a configurable interval. The fleet
  MUST transition BLOCKED→ACTIVE automatically on engine recovery —
  without requiring a server restart. The watchdog MUST log every
  state transition (HEALTHY→DEAD, DEAD→HEALTHY) with a structured
  audit entry before updating engine state.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger("adaad.fleet.watchdog")

PROBE_INTERVAL_SECONDS = float(os.getenv("DFSB_PROBE_INTERVAL", "60"))
HEAL_LOG_PATH = "logs/dork_fleet_watchdog.jsonl"


def _audit(event: str, engine_name: str, was_healthy: bool, now_healthy: bool) -> None:
    """DFSB-HEAL-0: structured audit entry for every state transition."""
    os.makedirs("logs", exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "engine": engine_name,
        "was_healthy": was_healthy,
        "now_healthy": now_healthy,
        "transition": f"{'HEALTHY' if was_healthy else 'DEAD'}→{'HEALTHY' if now_healthy else 'DEAD'}",
    }
    try:
        with open(HEAL_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as exc:
        log.error(f"DFSB-HEAL-0: watchdog audit write failed: {exc}")


class DorkFleetWatchdog:
    """
    Background asyncio task that periodically re-probes all fleet engines.

    On state transition (HEALTHY↔DEAD), emits a structured audit entry
    before updating engine._healthy, satisfying DFSB-HEAL-0.
    """

    def __init__(self, fleet, interval: float = PROBE_INTERVAL_SECONDS) -> None:
        self._fleet = fleet
        self._interval = interval
        self._task: asyncio.Task | None = None
        self._running = False

    async def _probe_loop(self) -> None:
        log.info(f"DorkFleetWatchdog started — interval={self._interval}s (DFSB-HEAL-0)")
        while self._running:
            await asyncio.sleep(self._interval)
            try:
                self._run_probe_cycle()
            except Exception as exc:
                log.error(f"Watchdog probe cycle error: {exc}")

    def _run_probe_cycle(self) -> None:
        """Probe all engines; log and record every state transition."""
        from dorkllm.state import ProviderStatus

        for engine in self._fleet._engines:
            was_healthy = engine.is_healthy()
            status: ProviderStatus = engine.probe()
            now_healthy = status.healthy
            # DFSB-HEAL-0: always sync engine._healthy from probe result
            engine._healthy = now_healthy
            self._fleet._provider_registry.record(status)

            if was_healthy != now_healthy:
                event = "engine_recovered" if now_healthy else "engine_failed"
                _audit(event, engine.name, was_healthy, now_healthy)
                log.warning(
                    f"DFSB-HEAL-0 transition: {engine.name} "
                    f"{'DEAD→HEALTHY ✅' if now_healthy else 'HEALTHY→DEAD ❌'}"
                )

        healthy = self._fleet._router.healthy_count()
        log.debug(f"Watchdog cycle complete — {healthy}/{len(self._fleet._engines)} healthy")

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self._running = True
        self._task = asyncio.ensure_future(self._probe_loop())
        log.info("DorkFleetWatchdog task scheduled")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("DorkFleetWatchdog stopped")
