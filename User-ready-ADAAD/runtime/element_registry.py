# SPDX-License-Identifier: Apache-2.0
"""
Element registry for five-element ownership tracking.
"""

from typing import Dict, List

from runtime import metrics

ELEMENT_ID = "Earth"

_REGISTRY: List[Dict[str, str]] = []


def register(element_id: str, module_name: str) -> None:
    """
    Register a module with its element ownership.
    """
    entry = {"element_id": element_id, "module": module_name}
    _REGISTRY.append(entry)
    metrics.log(
        event_type="element_registration",
        payload={"element_id": element_id, "module": module_name},
        level="INFO",
        element_id=element_id,
    )


def dump() -> List[Dict[str, str]]:
    """
    Return the registry snapshot and append it to the metrics stream.
    """
    metrics.log(
        event_type="element_registry_dump",
        payload={"registry": list(_REGISTRY)},
        level="INFO",
        element_id=ELEMENT_ID,
    )
    return list(_REGISTRY)
