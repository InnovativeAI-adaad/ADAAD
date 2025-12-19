from __future__ import annotations

from runtime.boot import boot_sequence


def run() -> dict:
    return boot_sequence()
