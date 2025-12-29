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

from app.agents import AGENTS_ROOT  # noqa: E402
from app.agents.base_agent import validate_agents  # noqa: E402


class AgentMetadataTest(unittest.TestCase):
    def test_agents_have_required_metadata(self):
        valid, errors = validate_agents(AGENTS_ROOT)
        self.assertTrue(valid, f"Agent metadata missing: {errors}")


if __name__ == "__main__":
    unittest.main()