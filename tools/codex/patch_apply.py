from __future__ import annotations

import subprocess
from pathlib import Path


def apply_patch(diff_path: Path) -> bool:
    diff_path = Path(diff_path)
    if not diff_path.exists():
        raise FileNotFoundError(f"Patch file not found: {diff_path}")
    if diff_path.read_text().strip() == "":
        return False
    result = subprocess.run(
        ["git", "apply", str(diff_path)], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"git apply failed: {result.stderr}")
    return True
