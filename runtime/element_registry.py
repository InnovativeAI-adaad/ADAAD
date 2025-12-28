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
Element registry for five-element ownership tracking.
"""

from typing import Dict, List

from runtime import metrics

ELEMENT_ID = "Earth"

_REGISTRY: List[Dict[str, str]] = []


def register(element_id: str, module_name: str) -> None:
    """
    Register a module with its element ownership.
    """
    entry = {"element_id": element_id, "module": module_name}
    _REGISTRY.append(entry)
    metrics.log(
        event_type="element_registration",
        payload={"element_id": element_id, "module": module_name},
        level="INFO",
        element_id=element_id,
    )


def dump() -> List[Dict[str, str]]:
    """
    Return the registry snapshot and append it to the metrics stream.
    """
    metrics.log(
        event_type="element_registry_dump",
        payload={"registry": list(_REGISTRY)},
        level="INFO",
        element_id=ELEMENT_ID,
    )
    return list(_REGISTRY)