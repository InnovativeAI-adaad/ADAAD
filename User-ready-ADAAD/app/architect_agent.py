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

"""
Architect agent responsible for scanning the workspace.
"""

from pathlib import Path
from typing import Dict, List

from app.agents.base_agent import validate_agents
from runtime import metrics

ELEMENT_ID = "Wood"


class ArchitectAgent:
    """
    Performs workspace scans and validates agent inventory.
    """

    def __init__(self, agents_root: Path):
        self.agents_root = agents_root

    def scan(self) -> Dict[str, List[str]]:
        valid, errors = validate_agents(self.agents_root)
        result = {"valid": valid, "errors": errors}
        level = "INFO" if valid else "ERROR"
        metrics.log(event_type="architect_scan", payload=result, level=level)
        return result