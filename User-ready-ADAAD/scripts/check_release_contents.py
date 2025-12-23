# SPDX-License-Identifier: Apache-2.0
"""
Guardrail to prevent brand assets from shipping in release artifacts.

Fails if any file under releases/ contains a brand/ segment, either on disk
or inside a .zip archive.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASES_DIR = REPO_ROOT / "releases"
BRAND_SEGMENT = "brand"


def _has_brand_segment(parts: tuple[str, ...]) -> bool:
    return BRAND_SEGMENT in parts


def check_directory_tree(root: Path) -> list[str]:
    failures: list[str] = []
    if not root.exists():
        return failures
    for path in root.rglob("*"):
        if _has_brand_segment(path.parts):
            failures.append(f"Brand asset found in releases: {path}")
        if path.is_file() and path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path, "r") as zf:
                    for name in zf.namelist():
                        if _has_brand_segment(tuple(Path(name).parts)):
                            failures.append(f"Brand asset inside archive {path}: {name}")
            except zipfile.BadZipFile:
                failures.append(f"Unreadable zip archive: {path}")
    return failures


def main() -> int:
    failures = check_directory_tree(RELEASES_DIR)
    if failures:
        for msg in failures:
            print(msg)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
