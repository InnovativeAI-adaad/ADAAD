# SPDX-License-Identifier: Apache-2.0
"""Minimal JSON health payload helper."""

from __future__ import annotations

import json
import time


def health_report(status: str = "ok", extra: dict | None = None) -> str:
    payload: dict[str, object] = {
        "status": status,
        "timestamp": time.time(),
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload)
