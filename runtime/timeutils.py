# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import time


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


__all__ = ["now_iso"]
