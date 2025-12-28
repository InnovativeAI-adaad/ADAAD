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

"""Reference agent implementing the ADAAD-required surface."""
from __future__ import annotations

from adad_core.evolve.mutator import mutate_source


INFO = {
    "id": "base_agent",
    "version": 1,
    "description": "Baseline agent that echoes input and stays deterministic.",
}


def info() -> dict:
    return INFO


def run(input=None) -> dict:
    message = str(input) if input is not None else "pong"
    return {"status": "ok", "echo": message}


def mutate(src: str) -> str:
    return mutate_source(src)


def score(output: dict) -> float:
    return 1.0 if output.get("status") == "ok" else 0.0


if __name__ == "__main__":
    run()