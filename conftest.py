# SPDX-License-Identifier: Apache-2.0
"""Global pytest path bootstrap for repository-local imports."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
