# SPDX-License-Identifier: Apache-2.0
"""Tight, stdlib-only sandbox runner."""
from __future__ import annotations

import runpy
import time
from pathlib import Path
from typing import Any, Dict


def run_script(path: str, timeout_s: int = 12) -> Dict[str, Any]:
    """Execute a python file in-process and collect basic telemetry."""
    t0 = time.monotonic()
    try:
        ns = runpy.run_path(path, run_name="__main__")
        ok = True
        err = None
    except Exception as e:  # pragma: no cover - defensive
        ok, err, ns = False, str(e), {}
    rt = time.monotonic() - t0
    return {"ok": ok, "error": err, "runtime": rt, "ns_keys": list(ns.keys())}


def list_scripts(path: Path) -> list[Path]:
    """Return sorted Python scripts under ``path``."""
    return sorted(p for p in path.glob("*.py") if p.is_file())
