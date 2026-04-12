# SPDX-License-Identifier: Apache-2.0
import subprocess
import sys


def test_no_duplicate_method_path_routes() -> None:
    cmd = [sys.executable, "scripts/validate_route_inventory.py", "--fail-on-duplicates", "--json"]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout or result.stderr
