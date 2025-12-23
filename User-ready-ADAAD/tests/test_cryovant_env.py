# SPDX-License-Identifier: Apache-2.0
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.append(str(ROOT))

from security import cryovant  # noqa: E402
from security.ledger import journal  # noqa: E402


class CryovantEnvironmentTest(unittest.TestCase):
    def test_ledger_and_keys_present(self):
        self.assertTrue(cryovant.validate_environment())
        ledger_file = journal.ensure_ledger()
        self.assertTrue(ledger_file.exists())
        self.assertTrue(os.access(ledger_file.parent, os.W_OK))
        keys_dir = ROOT / "security" / "keys"
        self.assertTrue(keys_dir.exists())


if __name__ == "__main__":
    unittest.main()
