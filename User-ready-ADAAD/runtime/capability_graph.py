# SPDX-License-Identifier: Apache-2.0
"""
Graph-backed capability registry enforcing dependencies and monotonic scores.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterable, List, Tuple

from runtime import ROOT_DIR, metrics

CAPABILITIES_PATH = ROOT_DIR / "data" / "capabilities.json"


def _load() -> Dict[str, Dict[str, Any]]:
    if not CAPABILITIES_PATH.exists():
        return {}
    try:
        return json.loads(CAPABILITIES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save(data: Dict[str, Dict[str, Any]]) -> None:
    CAPABILITIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CAPABILITIES_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _missing_dependencies(registry: Dict[str, Dict[str, Any]], requires: Iterable[str]) -> List[str]:
    return [req for req in requires if req not in registry]


def register_capability(
    name: str,
    version: str,
    score: float,
    owner_element: str,
    requires: List[str] | None = None,
    evidence: Dict[str, Any] | None = None,
) -> Tuple[bool, str]:
    """
    Register or update a capability while enforcing dependency presence and monotonic score.
    """

    requires = requires or []
    registry = _load()

    missing = _missing_dependencies(registry, requires)
    if missing:
        message = f"missing dependencies for {name}: {','.join(missing)}"
        metrics.log(
            event_type="capability_graph_rejected",
            payload={"name": name, "score": score, "reason": "missing_dependencies", "missing": missing},
            level="ERROR",
            element_id=owner_element,
        )
        return False, message

    existing = registry.get(name, {})
    try:
        existing_score = float(existing.get("score", -1))
    except (TypeError, ValueError):
        existing_score = -1

    if score < existing_score:
        message = f"score regression prevented for {name}"
        metrics.log(
            event_type="capability_graph_rejected",
            payload={
                "name": name,
                "score": score,
                "reason": "score_regression",
                "previous": existing_score,
            },
            level="ERROR",
            element_id=owner_element,
        )
        return False, message

    record = {
        "name": name,
        "version": version,
        "score": score,
        "owner": owner_element,
        "requires": list(requires),
        "evidence": evidence or {},
        "updated_at": _now(),
    }
    registry[name] = record
    _save(registry)
    metrics.log(
        event_type="capability_graph_registered",
        payload={
            "name": name,
            "version": version,
            "score": score,
            "owner": owner_element,
            "requires": list(requires),
        },
        level="INFO",
        element_id=owner_element,
    )
    return True, "ok"


def get_capabilities() -> Dict[str, Dict[str, Any]]:
    return _load()
