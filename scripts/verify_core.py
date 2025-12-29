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

"""
Cross-platform verification for ADAAD He65 rules.
"""

import re
import sys
from os import access, W_OK
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent

REQUIRED_DIRS = ["app", "runtime", "security", "tests", "docs", "data", "reports", "releases", "experiments", "scripts", "ui", "tools", "archives"]
BANNED_ROOTS = {"core", "engines", "adad_core", "ADAAD22"}


def ensure_dirs() -> None:
    for name in REQUIRED_DIRS:
        if not (TARGET / name).is_dir():
            sys.exit(f"Missing required directory: {name}")


def scan_imports() -> None:
    failures = []
    for path in TARGET.rglob("*.py"):
        if "archives" in path.parts:
            continue
        content = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(content, start=1):
            if line.startswith(("from ", "import ")):
                match = re.match(r"^(from|import) ([\\w\\.\\/]+)", line)
                if not match:
                    continue
                root = match.group(2).split(".")[0]
                if root in BANNED_ROOTS or root.startswith("/"):
                    failures.append(f"{path}:{lineno}:{line.strip()}")
    if failures:
        sys.exit("Banned imports detected:\\n" + "\\n".join(failures))


def ensure_metrics_and_security() -> None:
    metrics_file = TARGET / "reports" / "metrics.jsonl"
    metrics_file.parent.mkdir(parents=True, exist_ok=True)
    metrics_file.touch()

    ledger_dir = TARGET / "security" / "ledger"
    keys_dir = TARGET / "security" / "keys"
    if not ledger_dir.exists():
        sys.exit("Ledger directory missing")
    if not access(ledger_dir, W_OK):
        sys.exit("Ledger directory not writable")
    if not keys_dir.exists():
        sys.exit("Keys directory missing")


def main() -> None:
    ensure_dirs()
    scan_imports()
    ensure_metrics_and_security()
    print("Core verification passed.")


if __name__ == "__main__":
    main()