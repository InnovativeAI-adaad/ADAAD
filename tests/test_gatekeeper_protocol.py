# SPDX-License-Identifier: Apache-2.0

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from security.gatekeeper_protocol import run_gatekeeper


@contextmanager
def _in_temp_repo():
    prev_cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            for path in ("app", "runtime", "security/ledger", "security/keys"):
                Path(path).mkdir(parents=True, exist_ok=True)
            yield Path(tmp)
        finally:
            os.chdir(prev_cwd)


class GatekeeperProtocolTest(unittest.TestCase):
    def test_unchanged_files_have_no_drift(self) -> None:
        with _in_temp_repo():
            Path("app/alpha.txt").write_text("stable", encoding="utf-8")

            first = run_gatekeeper()
            second = run_gatekeeper()

            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertNotIn("drift", second)

    def test_content_change_with_same_path_flags_drift(self) -> None:
        with _in_temp_repo():
            target = Path("app/alpha.txt")
            target.write_text("version-a", encoding="utf-8")
            run_gatekeeper()

            target.write_text("version-b", encoding="utf-8")
            updated = run_gatekeeper()

            self.assertFalse(updated["ok"])
            self.assertTrue(updated.get("drift"))

    def test_path_add_or_remove_flags_drift(self) -> None:
        with _in_temp_repo():
            first = Path("app/first.txt")
            second = Path("app/second.txt")
            first.write_text("base", encoding="utf-8")
            run_gatekeeper()

            second.write_text("new", encoding="utf-8")
            added = run_gatekeeper()
            self.assertTrue(added.get("drift"))

            run_gatekeeper()
            second.unlink()
            removed = run_gatekeeper()
            self.assertTrue(removed.get("drift"))


if __name__ == "__main__":
    unittest.main()
