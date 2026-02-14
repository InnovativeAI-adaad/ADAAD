# SPDX-License-Identifier: Apache-2.0

import os
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch
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
            self.assertEqual(second["reasons"], [])
            self.assertIsNone(second["persistence_error"])

    def test_content_change_with_same_path_flags_drift(self) -> None:
        with _in_temp_repo():
            target = Path("app/alpha.txt")
            target.write_text("version-a", encoding="utf-8")
            run_gatekeeper()

            target.write_text("version-b", encoding="utf-8")
            updated = run_gatekeeper()

            self.assertFalse(updated["ok"])
            self.assertTrue(updated.get("drift"))
            self.assertIn("drift_detected", updated["reasons"])

    def test_path_add_or_remove_flags_drift(self) -> None:
        with _in_temp_repo():
            first = Path("app/first.txt")
            second = Path("app/second.txt")
            first.write_text("base", encoding="utf-8")
            run_gatekeeper()

            second.write_text("new", encoding="utf-8")
            added = run_gatekeeper()
            self.assertTrue(added.get("drift"))
            self.assertIn("drift_detected", added["reasons"])

            run_gatekeeper()
            second.unlink()
            removed = run_gatekeeper()
            self.assertTrue(removed.get("drift"))
            self.assertIn("drift_detected", removed["reasons"])

    def test_missing_paths_reason_code(self) -> None:
        with _in_temp_repo():
            Path("security/keys").rmdir()
            payload = run_gatekeeper()

            self.assertFalse(payload["ok"])
            self.assertIn("missing_paths", payload["reasons"])
            self.assertIn("security/keys", payload["missing"])

    def test_readonly_ledger_path_fails_closed(self) -> None:
        with _in_temp_repo():
            Path("app/alpha.txt").write_text("stable", encoding="utf-8")
            run_gatekeeper()

            with patch("pathlib.Path.write_text", side_effect=PermissionError("readonly")):
                payload = run_gatekeeper()

            self.assertFalse(payload["ok"])
            self.assertIn("hash_persist_failed", payload["reasons"])
            self.assertIsNotNone(payload["persistence_error"])

    def test_invalid_ledger_path_fails_closed(self) -> None:
        with _in_temp_repo():
            Path("app/alpha.txt").write_text("stable", encoding="utf-8")
            run_gatekeeper()

            ledger_dir = Path("security/ledger")
            ledger_dir.rename("security/ledger_backup")
            ledger_dir.write_text("not-a-directory", encoding="utf-8")
            payload = run_gatekeeper()

            self.assertFalse(payload["ok"])
            self.assertIn("hash_persist_failed", payload["reasons"])
            self.assertIsNotNone(payload["persistence_error"])


if __name__ == "__main__":
    unittest.main()
