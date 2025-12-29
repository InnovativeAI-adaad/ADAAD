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

"""Lightweight entry point for running a single ADAAD cycle."""
from __future__ import annotations

from adad_core.io.health import battery_allows_run, over_cpu_limit
from adad_core.runtime.pipeline import cycle_once


def main() -> None:
    if not battery_allows_run() or over_cpu_limit():
        print("[ADAD] Skipping: battery/CPU gate")
        return
    cycle_once()
    print("[ADAD] Cycle complete")


if __name__ == "__main__":
    main()