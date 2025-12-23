# SPDX-License-Identifier: Apache-2.0
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
