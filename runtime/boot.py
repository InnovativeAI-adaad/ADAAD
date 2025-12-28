from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List

from runtime.health import health_snapshot
from runtime.logger import get_logger
from runtime.registry import ELEMENTS, get_registry
from security.cryovant import Cryovant

if TYPE_CHECKING:
    from runtime.registry import ElementRegistry


def _agent_dirs(root: Path) -> List[Path]:
    """Return a deterministic list of agent directories under ``root``."""
    if not root.is_dir():
        return []
    return [path for path in sorted(root.iterdir(), key=lambda p: p.name) if path.is_dir()]


def _is_certified_agent(agent_dir: Path) -> bool:
    """Certified means certificate.json exists and has certified == True."""
    cert_path = agent_dir / "certificate.json"
    try:
        cert = json.loads(cert_path.read_text(encoding="utf-8"))
        return bool(cert.get("certified")) is True
    except Exception:
        return False


def _register_supporting_elements(
    *,
    registry: ElementRegistry,
    ledger_ok: bool,
    architect_scan: Dict[str, object] | None,
    dream_ready: object | None,
) -> Dict[str, object]:
    registry.register("water", ELEMENTS["water"][0], ELEMENTS["water"][1], {"ledger_ok": ledger_ok})
    registry.register("wood", ELEMENTS["wood"][0], ELEMENTS["wood"][1], architect_scan or {})
    registry.register("fire", ELEMENTS["fire"][0], ELEMENTS["fire"][1], dream_ready)
    registry.register("metal", ELEMENTS["metal"][0], ELEMENTS["metal"][1], {"ui_attached": (Path("ui/aponi_dashboard.py").exists())})
    return registry.snapshot()


def boot_sequence() -> Dict[str, object]:
    registry = get_registry()
    logger = get_logger(component="boot")
    status: Dict[str, object] = {}

    logger.audit("boot.preflight", actor="boot", outcome="start")
    health = health_snapshot()

    structure_ok = bool(health.get("structure_ok"))
    ledger_ok = bool(health.get("ledger_ok", False))

    registry.register("earth", ELEMENTS["earth"][0], ELEMENTS["earth"][1], {"structure_ok": structure_ok})

    if not structure_ok:
        raise RuntimeError("Required directories missing")
    if not ledger_ok:
        raise RuntimeError("Cryovant ledger not writable")

    cryo = Cryovant()
    cryo.ledger_probe(actor="boot")

    # Discover agents under app/agents/active/<agent_id>/
    agents_root = Path("app/agents/active")
    agents = _agent_dirs(agents_root)

    # Only certified agents can enable mutation
    certified_agents = [a for a in agents if _is_certified_agent(a)]

    logger.audit("boot.gatecheck", actor="boot", outcome="start", agents=len(agents), certified=len(certified_agents))

    mutation_enabled = bool(structure_ok and ledger_ok and certified_agents)
    safe_boot = not certified_agents

    if safe_boot:
        cryo.record_gate_rejection("no_certified_agents", "no_certified_agents", {"path": str(agents_root)})
        logger.audit("boot.runtime_ready", actor="boot", outcome="safe_boot", mutation_enabled=False)
    else:
        cryo.gate_cycle(certified_agents)
        logger.audit("boot.runtime_ready", actor="boot", outcome="ready", mutation_enabled=mutation_enabled)

    status.update(health)
    status.update(
        {
            "cryovant_ready": ledger_ok,
            "mutation_enabled": mutation_enabled,
            "elements": _register_supporting_elements(
                registry=registry,
                ledger_ok=ledger_ok,
                architect_scan=health.get("architect_scan"),
                dream_ready=health.get("dream_ready"),
            ),
            "safe_boot": safe_boot,
        }
    )

    return status


__all__ = ["boot_sequence"]
