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

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.append(str(ROOT))

from runtime import metrics  # noqa: E402


class MetricsWriteTest(unittest.TestCase):
    def test_metrics_append(self):
        metrics.log(event_type="unittest_probe", payload={"ok": True}, level="INFO")
        entries = metrics.tail(limit=5)
        self.assertTrue(any(entry.get("event") == "unittest_probe" for entry in entries))


if __name__ == "__main__":
    unittest.main()