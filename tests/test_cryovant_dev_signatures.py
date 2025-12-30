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

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from security import cryovant


class CryovantDevSignatureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_root = Path(self.tmp.name)
        self.agents_root = self.tmp_root / "agents"
        self.agents_root.mkdir(parents=True, exist_ok=True)
        os.environ.pop("CRYOVANT_DEV_MODE", None)

        self._orig_keys_dir = cryovant.KEYS_DIR
        cryovant.KEYS_DIR = self.tmp_root / "keys"
        self.addCleanup(setattr, cryovant, "KEYS_DIR", self._orig_keys_dir)
        cryovant.KEYS_DIR.mkdir(parents=True, exist_ok=True)

    def test_certify_accepts_dev_signature_without_dev_mode(self) -> None:
        agent = self.agents_root / "sample"
        agent.mkdir()
        (agent / "meta.json").write_text(json.dumps({"name": "sample"}), encoding="utf-8")
        (agent / "dna.json").write_text(json.dumps({"traits": []}), encoding="utf-8")
        (agent / "certificate.json").write_text(json.dumps({"signature": "cryovant-dev-sample"}), encoding="utf-8")

        with mock.patch("security.cryovant.metrics.log"), mock.patch("security.cryovant.journal.write_entry"):
            ok, errors = cryovant.certify_agents(self.agents_root)

        self.assertTrue(ok)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
