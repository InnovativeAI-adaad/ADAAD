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

"""Simple AST/text mutator for agents."""
from __future__ import annotations

import ast
import random
import time
from typing import Callable


def mutate_source(src: str) -> str:
    """Attempt to shuffle function bodies; fall back to a text append."""
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.body:
                random.shuffle(node.body)
        return ast.unparse(tree)
    except Exception:
        ts = int(time.time())
        return src + f"\n# mutation_fallback @ {ts}\n"


Mutator = Callable[[str], str]