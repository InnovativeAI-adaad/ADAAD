# SPDX-License-Identifier: Apache-2.0
"""Preloaded handler registry for O(1) lookup dispatch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Handler = Callable[[Any], Any]


class HandlerRegistry:
    """Simple dict-backed registry with O(1) handler lookups."""

    def __init__(self, handlers: dict[str, Handler] | None = None) -> None:
        self._handlers: dict[str, Handler] = dict(handlers or {})

    @classmethod
    def preload(cls, handlers: dict[str, Handler]) -> "HandlerRegistry":
        return cls(handlers=handlers)

    def register(self, key: str, handler: Handler) -> None:
        self._handlers[key] = handler

    def get(self, key: str) -> Handler:
        return self._handlers[key]

    def has(self, key: str) -> bool:
        return key in self._handlers


# Compatibility procedural API
_DEFAULT_REGISTRY = HandlerRegistry()


def register_tool(name: str, run_tool: Callable[..., Any]) -> None:
    _DEFAULT_REGISTRY.register(name, run_tool)  # type: ignore[arg-type]


def get_tool(name: str) -> Callable[..., Any]:
    return _DEFAULT_REGISTRY.get(name)  # type: ignore[return-value]


def clear_registry() -> None:
    _DEFAULT_REGISTRY._handlers.clear()


def registry_snapshot() -> dict[str, Callable[..., Any]]:
    return dict(_DEFAULT_REGISTRY._handlers)


__all__ = ["Handler", "HandlerRegistry", "register_tool", "get_tool", "clear_registry", "registry_snapshot"]
