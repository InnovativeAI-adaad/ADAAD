# SPDX-License-Identifier: Apache-2.0
"""Bootstrap registration for orchestrator tools."""

from __future__ import annotations

from importlib import import_module
from threading import Lock
from typing import Callable, Sequence, Tuple

from adaad.orchestrator.registry import register_tool

ToolSpec = Tuple[str, str]

_DEFAULT_TOOL_SPECS: Sequence[ToolSpec] = (
    ("mutation.apply_dna", "runtime.tools.mutation_guard:apply_dna_mutation"),
    ("mutation.apply_code", "runtime.tools.code_mutation_guard:apply_code_mutation"),
    ("mutation.extract_code_targets", "runtime.tools.code_mutation_guard:extract_targets"),
    ("mutation.apply_ops", "runtime.tools.mutation_guard:_apply_ops"),
)

_BOOTSTRAPPED = False
_LOCK = Lock()


def _load_callable(spec: str) -> Callable:
    module_name, attr_name = spec.split(":", 1)
    module = import_module(module_name)
    fn = getattr(module, attr_name)
    if not callable(fn):
        raise TypeError(f"bootstrap_target_not_callable:{spec}")
    return fn


def bootstrap_tool_registry(tool_specs: Sequence[ToolSpec] | None = None) -> None:
    """Register all tool callables once at startup."""
    global _BOOTSTRAPPED
    with _LOCK:
        if _BOOTSTRAPPED:
            return
        specs = tool_specs or _DEFAULT_TOOL_SPECS
        for tool_name, import_spec in specs:
            register_tool(tool_name, _load_callable(import_spec))
        _BOOTSTRAPPED = True
