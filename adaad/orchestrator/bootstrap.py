# SPDX-License-Identifier: Apache-2.0
"""Bootstrap registration for orchestrator tools."""

from __future__ import annotations

from threading import Lock
from typing import Callable, Sequence, Tuple

from adaad.orchestrator.registry import register_tool

ToolSpec = Tuple[str, str]

_DEFAULT_TOOL_SPECS: Sequence[ToolSpec] = (
    ("mutation.apply_dna", "runtime.tools.mutation_guard:apply_dna_mutation"),
    ("mutation.apply_code", "runtime.tools.code_mutation_guard:apply_code_mutation"),
    ("mutation.extract_code_targets", "runtime.tools.code_mutation_guard:extract_targets"),
    ("mutation.apply_ops", "runtime.tools.mutation_guard:_apply_ops"),
    # Self-capable abilities integration (enhance all of ADAAD with high-level self-awareness)
    ("abilities.list", "adaad.abilities:list_abilities"),
    ("abilities.discover", "adaad.abilities.discovery:discover_abilities"),
    ("abilities.drift", "adaad.abilities.drift:detect_abilities_drift"),
    ("abilities.snapshot", "adaad.abilities.registry:abilities_snapshot"),
)

_BOOTSTRAPPED = False
_LOCK = Lock()


def _load_callable(spec: str) -> Callable:
    # lint:fix forbidden_dynamic_execution — explicit callable routing — governance-reviewed
    if spec == "runtime.tools.mutation_guard:apply_dna_mutation":
        from runtime.tools.mutation_guard import apply_dna_mutation

        fn = apply_dna_mutation
    elif spec == "runtime.tools.code_mutation_guard:apply_code_mutation":
        from runtime.tools.code_mutation_guard import apply_code_mutation

        fn = apply_code_mutation
    elif spec == "runtime.tools.code_mutation_guard:extract_targets":
        from runtime.tools.code_mutation_guard import extract_targets

        fn = extract_targets
    elif spec == "runtime.tools.mutation_guard:_apply_ops":
        from runtime.tools.mutation_guard import _apply_ops

        fn = _apply_ops
    elif spec.startswith("builtins:"):
        import builtins
        attr = spec.split(":", 1)[1]
        fn = getattr(builtins, attr)
    elif spec == "adaad.abilities:list_abilities":
        from adaad.abilities import list_abilities
        fn = list_abilities
    elif spec == "adaad.abilities.discovery:discover_abilities":
        from adaad.abilities.discovery import discover_abilities
        fn = discover_abilities
    elif spec == "adaad.abilities.drift:detect_abilities_drift":
        from adaad.abilities.drift import detect_abilities_drift
        fn = detect_abilities_drift
    elif spec == "adaad.abilities.registry:abilities_snapshot":
        from adaad.abilities.registry import abilities_snapshot
        fn = abilities_snapshot
    else:
        raise ModuleNotFoundError(f"bootstrap_target_not_registered:{spec}")
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

        # Enhance all of ADAAD: install the constitutional abilities governance hook
        # at bootstrap time (self-governed registration for abilities surface).
        # Uses the bridge for lazy CMES/CGDR wiring; fail-soft for isolation.
        try:
            from adaad.orchestrator.abilities_bridge import install_constitutional_ability_hook  # adaad: import-boundary-ok:bootstrap-self-governance
            install_constitutional_ability_hook(enable_cmes_trial=False)
        except Exception:
            pass  # keep boot robust; hook is optional/enhancement
