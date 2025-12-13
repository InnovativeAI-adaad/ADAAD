from __future__ import annotations

from pathlib import Path
import time

from runtime.bootstrap import init_runtime_environment, init_logging
from runtime.warm_pool import WarmPool
from runtime.health import HealthChecks
from security.cryovant import Cryovant, secure_append_jsonl
from app.architect_agent import ArchitectAgent
from app.dream_mode import DreamMode
try:
    from app.beast_mode_loop import BeastModeLoop  # type: ignore
except Exception:  # pragma: no cover - fallback stub
    class BeastModeLoop:
        def __init__(self, *_, **__):
            self._enabled = False

        def enable(self):
            self._enabled = True

        def disable(self):
            self._enabled = False

        def heartbeat_loop(self):
            while self._enabled:
                time.sleep(5)

        def shutdown(self):
            self._enabled = False


BASE = Path(__file__).resolve().parents[1]
REPORTS = BASE / "reports"
cryo = None  # set in main()


def emit_metric(payload: dict):
    if cryo is None:
        raise RuntimeError("Cryovant is not initialized")
    secure_append_jsonl(cryo, REPORTS / "metrics.jsonl", payload)  # policy allows reports writes


def main():
    init_runtime_environment(BASE)
    init_logging(REPORTS / "health.log")

    global cryo
    cryo = Cryovant(BASE / "security/ledger", BASE / "security/keys", metrics_sink=emit_metric)
    ok = HealthChecks.ledger_write(cryo)

    architect = ArchitectAgent(BASE)
    ok &= HealthChecks.architect_scan(architect.quick_scan())

    dream = DreamMode(BASE, cryo)
    try:
        beast = BeastModeLoop(BASE, cryo)
    except Exception:
        class BeastModeLoop:
            def __init__(self, *a, **k):
                self._enabled = False

            def enable(self):
                self._enabled = True

            def disable(self):
                self._enabled = False

            def heartbeat_loop(self):
                while self._enabled:
                    time.sleep(5)

            def shutdown(self):
                self._enabled = False

        beast = BeastModeLoop()

    agents_roots = [BASE / "app/agents/builtin", BASE / "app/agents/lineage"]
    agent_dirs = [p for root in agents_roots for p in Path(root).glob("*") if p.is_dir()]
    cert_ok = ok and cryo.gate_cycle(agent_dirs)

    ENGINES = {  # explicit registry for introspection
        "architect": architect,
        "dream": dream,
        "beast": beast,
    }

    # WOOD audit before entering the main loop.
    audit = architect.engine_state_audit(ENGINES, cert_ok=bool(cert_ok), health_ok=bool(ok))
    emit_metric({"event_type": "ENGINE_STATE_AUDIT", "status": audit.get("status"), "audit": audit})

    if cert_ok:
        dream.enable()
        beast.enable()
    else:
        emit_metric({"event_type": "HARD_GATE", "status": "ENGINES_DISABLED", "reason": "cryovant_gate_failed"})
        dream.disable()
        beast.disable()

    pool = WarmPool(max_workers=4)
    pool.submit(dream.background_housekeeping)
    pool.submit(beast.heartbeat_loop)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        beast.shutdown()
        dream.shutdown()
        pool.shutdown()


if __name__ == "__main__":
    main()
