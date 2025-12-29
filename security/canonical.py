from __future__ import annotations

import json
from typing import Any, Dict


def canonical_json(obj: Dict[str, Any]) -> str:
    """Return deterministic JSON for signing and hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_mac_input(
    agent_id: str,
    mutation_type: str,
    payload: Dict[str, Any],
    nonce: str,
    timestamp: str,
    challenge_id: str,
    challenge: str,
) -> Dict[str, Any]:
    return {
        "agent_id": agent_id,
        "mutation_type": mutation_type,
        "payload": payload,
        "nonce": nonce,
        "timestamp": timestamp,
        "challenge_id": challenge_id,
        "challenge": challenge,
    }


__all__ = [
    "canonical_json",
    "build_mac_input",
]
