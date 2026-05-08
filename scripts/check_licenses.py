# SPDX-License-Identifier: Apache-2.0
"""
Fail-fast license guardrail.

Checks:
- No CC-license references in repository-authored files.
- No HTTP Apache license URLs.
- Root licensing artifacts align with the current proprietary distribution license.
- Python files that declare SPDX use the exact Apache-2.0 source-header identifier.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APACHE_HTTP = "http" + "://www.apache.org/licenses"
CC_TOKEN = "Creative" + " Commons"
CC0_TOKEN = "CC" + "0"
VALID_SPDX_TAG = "# SPDX-License-Identifier: Apache-2.0"
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".pdf", ".mp4", ".mov", ".sqlite", ".db"}


def tracked_files(root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    files: list[Path] = []
    for line in completed.stdout.splitlines():
        path = root / line.strip()
        if path.is_file():
            files.append(path)
    return files


def _check_proprietary_baseline(failures: list[str]) -> None:
    license_text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8", errors="ignore")
    if "Proprietary Software License" not in license_text:
        failures.append("Root LICENSE does not contain Proprietary Software License header")
    if "Prior versions distributed under Apache License 2.0" not in license_text:
        failures.append("Root LICENSE does not preserve prior Apache-2.0 version notice")

    licenses_md = (REPO_ROOT / "LICENSES.md").read_text(encoding="utf-8", errors="ignore")
    if "Proprietary" not in licenses_md:
        failures.append("LICENSES.md does not reference proprietary baseline")

    notice_text = (REPO_ROOT / "NOTICE").read_text(encoding="utf-8", errors="ignore")
    if "Proprietary" not in notice_text:
        failures.append("NOTICE does not reference proprietary licensing")


def main() -> int:
    failures: list[str] = []

    _check_proprietary_baseline(failures)

    for path in tracked_files(REPO_ROOT):
        if path.name == "check_licenses.py":
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if CC_TOKEN in text or CC0_TOKEN in text:
            failures.append(f"CC-license reference found in {path.relative_to(REPO_ROOT)}")
        if APACHE_HTTP in text:
            failures.append(f"HTTP Apache URL found in {path.relative_to(REPO_ROOT)}")

        if path.suffix == ".py":
            head = text.splitlines()[:25]
            spdx_lines = [line for line in head if line.startswith("# SPDX-License-Identifier:")]
            if spdx_lines and any(line != VALID_SPDX_TAG for line in spdx_lines):
                failures.append(f"Invalid SPDX tag in {path.relative_to(REPO_ROOT)}")

    if failures:
        for line in failures:
            print(line)
        return 1
    print("License checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
