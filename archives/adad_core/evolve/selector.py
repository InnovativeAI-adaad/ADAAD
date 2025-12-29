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

"""Selection rules for promoting or quarantining agents."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PROMOTE_THRESHOLD = 0.75
QUARANTINE_THRESHOLD = 0.30


@dataclass
class SelectionResult:
    path: Path
    fitness: float
    action: str  # "promotion", "quarantine", or "retain"


def select_action(path: Path, fitness: float) -> SelectionResult:
    if fitness >= PROMOTE_THRESHOLD:
        action = "promotion"
    elif fitness <= QUARANTINE_THRESHOLD:
        action = "quarantine"
    else:
        action = "retain"
    return SelectionResult(path=path, fitness=fitness, action=action)


def summarize(results: Iterable[SelectionResult]) -> dict:
    counts = {"promotion": 0, "quarantine": 0, "retain": 0}
    for result in results:
        counts[result.action] = counts.get(result.action, 0) + 1
    return counts