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