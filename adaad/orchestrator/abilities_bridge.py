# SPDX-License-Identifier: Apache-2.0
"""Thin bridge for wiring adaad/abilities governance hook to constitutional self-mutation stack.

This lives in adaad/orchestrator (controlled import surface) so the core
adaad/abilities package remains lightweight and importable alone.

The factory returns a hook callable suitable for
adaad.abilities.registry.set_governance_hook(...).

The hook (when invoked on register_ability):
- Lazily checks CGDR healthy (if the reporter is importable) — blocks on DRIFTED per AMPS-CGDR-0 pattern.
- Optionally opens a CMES sandbox "trial" for the registration (captures registry snapshot delta as BehavioralDelta-like evidence).
- On success allows the insert; on any gate failure raises (fail-closed).

Heavy imports (dorkllm.*, app/api/*) are inside the hook / factory, never at module level.
"adaad: import-boundary-ok" comments are used for the known controlled crossings.

This enables the "self capable" loop: abilities can be proposed, trialed in CMES,
admitted, and promoted while the lightweight surface stays early-import safe.
"""

from __future__ import annotations

from typing import Any, Callable

from adaad.abilities.base import Ability

# Type for the hook passed to set_governance_hook
AbilityGovernanceHook = Callable[[Ability], None]


def make_constitutional_ability_hook(*, enable_cmes_trial: bool = False) -> AbilityGovernanceHook:
    """Return a hook that enforces constitutional gates before ability registration.

    enable_cmes_trial=True will attempt a lightweight CMES open/execute using a
    dry-run spec for the abilities surface (best-effort; requires the sandbox
    impl to be importable). Defaults to gate checks only (CGDR healthy).

    The returned hook is safe to install early; all heavy work is lazy.
    """

    def _hook(ability: Ability) -> None:
        # 1. CGDR healthy gate (AMPS-CGDR-0 / CGDR-GATE-0 pattern)
        try:
            # Lazy import — never at module level
            from dorkllm.convergence_governance_drift_reporter import ConvergenceGovernanceDriftReporter  # adaad: import-boundary-ok:abilities-cgdr
            cgdr = ConvergenceGovernanceDriftReporter()
            status = cgdr.get_status().get("gate_status", "UNKNOWN")
            if status in ("DRIFTED", "UNKNOWN"):
                raise RuntimeError(f"ABILITY-CGDR-0: CGDR gate {status}; cannot register {ability.name}")
        except Exception as exc:
            # If CGDR not available in this context, fail-closed for high-stakes
            # (callers doing pure local/dev discovery can use the default no-op hook).
            # For self-extension under governance we require the check.
            # To keep import-alone for pure discovery use, we only hard-fail when
            # the caller has explicitly asked for the constitutional hook.
            # Here we re-raise a specific message so upper layers can decide.
            raise RuntimeError(f"ABILITY-CGDR-0: CGDR healthy check failed or unavailable: {exc}") from exc

        # 2. Optional CMES trial for the registration effect (delta on snapshot)
        if enable_cmes_trial:
            try:
                # Lazy, guarded
                from dorkllm.constitutional_mutation_execution_sandbox import (  # adaad: import-boundary-ok:abilities-cmes
                    ConstitutionalMutationExecutionSandbox,
                    CMESSandboxLedger,
                    MutationSpec,
                    BlastRadius,
                )
                sandbox = ConstitutionalMutationExecutionSandbox(ledger=CMESSandboxLedger())
                # Minimal spec targeting the abilities surface
                spec = MutationSpec(
                    mutation_id=f"ability-reg-{ability.name}",
                    module_path="adaad/abilities/registry.py",
                    blast_radius=BlastRadius.TIER1,
                    description=f"Trial register of high-level ability {ability.name}",
                    invariants_targeted=["ABILITY-REG-HOOK-0"],
                    proposed_by="adaad.abilities.self",
                )
                run = sandbox.open_sandbox(spec)
                # Execute (the sandbox will capture BehavioralDelta including registry effects in real wiring)
                run = sandbox.execute(run.run_id)
                if getattr(run, "status", None) and str(run.status).upper() not in ("PASSED", "PASS"):
                    raise RuntimeError(f"ABILITY-CMES-0: CMES trial failed for {ability.name}: {getattr(run, 'failure_reason', 'unknown')}")
            except Exception as exc:
                raise RuntimeError(f"ABILITY-CMES-0: CMES trial error (enable_cmes_trial=True): {exc}") from exc

        # If we reach here, gates passed (or were skipped gracefully for the trial).
        # The actual insert happens in register_ability after this hook returns.
        return

    return _hook


def install_constitutional_ability_hook(*, enable_cmes_trial: bool = False) -> None:
    """Convenience: install the constitutional hook into the live abilities registry."""
    from adaad.abilities.registry import set_governance_hook
    hook = make_constitutional_ability_hook(enable_cmes_trial=enable_cmes_trial)
    set_governance_hook(hook)


__all__ = [
    "make_constitutional_ability_hook",
    "install_constitutional_ability_hook",
    "AbilityGovernanceHook",
]