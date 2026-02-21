# SPDX-License-Identifier: Apache-2.0
"""Canonical ADAAD root resolution."""

from __future__ import annotations

import os
from pathlib import Path


def get_root_dir() -> Path:
    """Resolve ADAAD repository root with optional environment override."""
    env_root = (os.environ.get("ADAAD_ROOT") or "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()
    # .../adaad/core/root.py -> repository root is parents[2]
    return Path(__file__).resolve().parents[2]


ROOT_DIR = get_root_dir()
