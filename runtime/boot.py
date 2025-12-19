from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from runtime.health import health_snapshot
from runtime.registry import ELEMENTS, get_registry
from security.cryovant import Cryovant


def _agent_dirs(root: Path) -> List[Path]:
    if not root.exists():
        return []
    return [p for p in root.iterdir() if p.is_dir()]


def boot_sequence() -> Dict[str, object]:
    registry = get_registry()
    status: Dict[str, object] = {"elements": {}}

    health = health_snapshot()
    status.update(health)

    structure_ok = bool(health.get("structure_ok"))
    ledger_ok = bool(health.get("ledger_ok", False))

    registry.register("earth", ELEMENTS["earth"][0], ELEMENTS["earth"][1], {"structure_ok": structure_ok})

    if not structure_ok:
        raise RuntimeError("Required directories missing")
    if not ledger_ok:
        raise RuntimeError("Cryovant ledger not writable")

    cryo = Cryovant()
    agents_root = Path("app/agents/active")
    agents = _agent_dirs(agents_root)
    cryo.gate_cycle(agents)
    registry.register("water", ELEMENTS["water"][0], ELEMENTS["water"][1], {"ledger_ok": True})

    registry.register("wood", ELEMENTS["wood"][0], ELEMENTS["wood"][1], health.get("architect_scan", {}))
    registry.register("fire", ELEMENTS["fire"][0], ELEMENTS["fire"][1], health.get("dream_ready"))
    registry.register("metal", ELEMENTS["metal"][0], ELEMENTS["metal"][1], {"ui_attached": False})

    mutation_enabled = structure_ok and ledger_ok

    status.update(
        {
            "cryovant_ready": ledger_ok,
            "mutation_enabled": mutation_enabled,
            "elements": registry.snapshot(),
        }
    )

    return status


__all__ = ["boot_sequence"]
