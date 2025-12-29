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

"""Cheap deterministic IQ-like probes."""
from __future__ import annotations

from typing import List


def reverse_compare(text: str) -> float:
    """Return 1.0 if reversing twice yields the original string."""
    return 1.0 if text == text[::-1][::-1] else 0.0


def checksum_digits(n: int) -> float:
    """Return 1.0 if the digit sum is stable under modulo 9."""
    total = sum(int(d) for d in str(abs(n)))
    return 1.0 if total % 9 == n % 9 else 0.0


def run_iq_tasks(seed: str) -> List[float]:
    """Execute a deterministic bundle of probes."""
    values = [ord(c) for c in seed] or [0]
    anchor = (sum(values) + len(values)) % 9973
    return [reverse_compare(seed), checksum_digits(anchor)]