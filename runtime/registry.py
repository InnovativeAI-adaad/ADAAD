from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping


@dataclass
class Element:
    name: str
    path: str
    purpose: str
    registered: bool = False
    details: Dict[str, object] = field(default_factory=dict)


class ElementRegistry:
    def __init__(self) -> None:
        self.elements: Dict[str, Element] = {}

    def register(self, element_id: str, path: str, purpose: str, details: Dict[str, object] | None = None) -> Element:
        if element_id in self.elements:
            # Idempotent registration: boot_sequence may run multiple times in-process.
            existing = self.elements.get(element_id)
            if existing is not None:
                # Keep first path/purpose. Refresh details.
                try:
                    existing.details = details
                except Exception:
                    pass
                return existing
            raise ValueError(f"Element '{element_id}' already registered")

        elem = Element(name=element_id, path=path, purpose=purpose, registered=True, details=details or {})
        self.elements[element_id] = elem
        return elem

    def snapshot(self) -> Dict[str, object]:
        return {k: vars(v) for k, v in self.elements.items()}


ELEMENTS = {
    "earth": ("runtime", "Runtime baseline and governance"),
    "wood": ("app/architect_agent.py", "Architect scans and structural planning"),
    "fire": ("app/dream_mode.py", "Dream and beast loops discovery"),
    "water": ("security/cryovant.py", "Cryovant ledger and certification"),
    "metal": ("ui/aponi_dashboard.py", "Aponi dashboard attach point"),
}

_REGISTRY = ElementRegistry()


def get_registry() -> ElementRegistry:
    return _REGISTRY


def register(element_id: str, path: str, purpose: str, details: Dict[str, object] | None = None) -> Element:
    return _REGISTRY.register(element_id, path, purpose, details)


def snapshot() -> Mapping[str, object]:
    return _REGISTRY.snapshot()


__all__ = ["Element", "ELEMENTS", "register", "snapshot", "get_registry", "ElementRegistry"]
