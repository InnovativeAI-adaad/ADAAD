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

import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


# Approved top-level namespaces for in-repo imports.
# To add a new namespace:
# 1) Create the top-level package/module at the repo root.
# 2) Add the new namespace to APPROVED_ROOTS below.
# 3) Ensure imports use the new root instead of legacy ones.
APPROVED_ROOTS = {"app", "governance", "runtime", "security", "ui", "tests", "tools", "warnings"}
STDLIB_ROOTS = set(getattr(sys, "stdlib_module_names", ())) | set(sys.builtin_module_names) | {"warnings"}
SITE_PACKAGES_MARKERS = ("site-packages", "dist-packages")
EXCLUDED_DIRS = {".venv", "venv", "__pycache__", ".tox", ".mypy_cache", "build", "dist", "archives"}


def is_excluded_path(path: Path) -> bool:
    if path.name == "mutation_budget_manager.py":
        return True
    return any(part in EXCLUDED_DIRS for part in path.parts)


class ImportRootTest(unittest.TestCase):
    def test_no_legacy_import_roots(self):
        failures = []
        for path in ROOT.rglob("*.py"):
            if is_excluded_path(path):
                continue
            content = path.read_text(encoding="utf-8").splitlines()
            for lineno, line in enumerate(content, start=1):
                if line.startswith(("from ", "import ")):
                    match = re.match(r"^(from|import) ([\\w\\.\\/]+)", line)
                    if not match:
                        continue
                    module = match.group(2)
                    if module.startswith("."):
                        continue
                    root = module.split(".")[0]
                    if root.startswith("/"):
                        failures.append(f"{path}:{lineno}:{line.strip()}")
                        continue
                    if root in APPROVED_ROOTS or root in STDLIB_ROOTS:
                        continue
                    spec = importlib.util.find_spec(root)
                    if spec is not None:
                        origin = spec.origin or ""
                        if origin == "built-in":
                            continue
                        if any(marker in origin for marker in SITE_PACKAGES_MARKERS):
                            continue
                    failures.append(f"{path}:{lineno}:{line.strip()}")
        self.assertFalse(failures, f"Disallowed import roots found: {failures}")


if __name__ == "__main__":
    unittest.main()
