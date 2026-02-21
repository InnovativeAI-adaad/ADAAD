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

        self._orig_keys_dir = cryovant.KEYS_DIR
        cryovant.KEYS_DIR = self.tmp_root / "keys"
        self.addCleanup(setattr, cryovant, "KEYS_DIR", self._orig_keys_dir)
        cryovant.KEYS_DIR.mkdir(parents=True, exist_ok=True)

        self._orig_adaad_env = os.environ.get("ADAAD_ENV")
        self._orig_dev_mode = os.environ.get("CRYOVANT_DEV_MODE")
        self.addCleanup(self._restore_env)

    def _restore_env(self) -> None:
        if self._orig_adaad_env is None:
            os.environ.pop("ADAAD_ENV", None)
        else:
            os.environ["ADAAD_ENV"] = self._orig_adaad_env

        if self._orig_dev_mode is None:
            os.environ.pop("CRYOVANT_DEV_MODE", None)
        else:
            os.environ["CRYOVANT_DEV_MODE"] = self._orig_dev_mode

    def test_prod_without_keys_rejects_dev_signature(self) -> None:
        os.environ["ADAAD_ENV"] = "prod"
        os.environ.pop("CRYOVANT_DEV_MODE", None)

        with mock.patch("security.cryovant.metrics.log") as metrics_log:
            self.assertFalse(cryovant.signature_valid("cryovant-dev-sample"))

        metrics_log.assert_called_once()
        self.assertEqual(metrics_log.call_args.kwargs["event_type"], "cryovant_signature_verification_without_keys")
        self.assertEqual(metrics_log.call_args.kwargs["level"], "CRITICAL")

    def test_dev_with_dev_mode_accepts_dev_signature(self) -> None:
        os.environ["ADAAD_ENV"] = "dev"
        os.environ["CRYOVANT_DEV_MODE"] = "1"

        with mock.patch("security.cryovant.metrics.log") as metrics_log:
            self.assertTrue(cryovant.signature_valid("cryovant-dev-sample"))

        event_types = [call.kwargs.get("event_type") for call in metrics_log.call_args_list]
        self.assertIn("cryovant_signature_verification_without_keys", event_types)
        self.assertIn("cryovant_dev_signature_accepted", event_types)

    def test_prod_valid_real_signature_accepts(self) -> None:
        os.environ["ADAAD_ENV"] = "prod"
        (cryovant.KEYS_DIR / "signing-key.pem").write_text("key", encoding="utf-8")

        with mock.patch("security.cryovant.verify_signature", return_value=True), mock.patch(
            "security.cryovant.metrics.log"
        ) as metrics_log:
            self.assertTrue(cryovant.signature_valid("real-signature"))

        metrics_log.assert_not_called()


if __name__ == "__main__":
    unittest.main()
