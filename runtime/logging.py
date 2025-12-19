# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
"""Compatibility shim forwarding to the canonical JSON logger."""
from __future__ import annotations

from typing import Any

from runtime.logger import get_logger

_shim_logger = get_logger(component="runtime")


def event(name: str, **data: Any) -> None:
    _shim_logger.info(name, **data)


__all__ = ["event"]
