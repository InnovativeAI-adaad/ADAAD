# SPDX-License-Identifier: Apache-2.0
"""Repository-level license compliance validator.

This wrapper exists to provide a stable CI command name while delegating
validation logic to `scripts/check_licenses.py`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "check_licenses.py")]
    completed = subprocess.run(cmd, cwd=REPO_ROOT, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
