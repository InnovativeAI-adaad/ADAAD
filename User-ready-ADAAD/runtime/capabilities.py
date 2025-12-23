"""
Monotonic capability registry.
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple

from runtime import ROOT_DIR, metrics

ELEMENT_ID = "Earth"

CAPABILITIES_PATH = ROOT_DIR / "data" / "capabilities.json"


def _load() -> Dict[str, Dict[str, str | float]]:
    if not CAPABILITIES_PATH.exists():
        return {}
    try:
        return json.loads(CAPABILITIES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save(data: Dict[str, Dict[str, str | float]]) -> None:
    CAPABILITIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CAPABILITIES_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def register_capability(name: str, version: str, score: float, owner_element: str) -> Tuple[bool, str]:
    """
    Register or update a capability score, enforcing monotonic non-decreasing scores.
    """
    registry = _load()
    existing = registry.get(name, {})
    existing_score = float(existing.get("score", -1))
    if score < existing_score:
        message = f"score regression prevented for {name}"
        metrics.log(event_type="capability_rejected", payload={"name": name, "score": score}, level="ERROR", element_id=ELEMENT_ID)
        return False, message

    registry[name] = {"version": version, "score": score, "owner": owner_element}
    _save(registry)
    metrics.log(
        event_type="capability_registered",
        payload={"name": name, "version": version, "score": score, "owner": owner_element},
        level="INFO",
        element_id=ELEMENT_ID,
    )
    return True, "ok"


def get_capabilities() -> Dict[str, Dict[str, str | float]]:
    return _load()
