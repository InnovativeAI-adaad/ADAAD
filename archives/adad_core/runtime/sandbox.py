# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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