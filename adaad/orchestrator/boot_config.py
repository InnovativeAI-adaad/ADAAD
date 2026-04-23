# SPDX-License-Identifier: Apache-2.0
"""Typed orchestration facade boot configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from runtime.api.runtime_services import ReplayMode, normalize_replay_mode


@dataclass(frozen=True)
class OrchestratorInitState:
    """Normalized orchestrator initialization inputs used by the CLI facade."""

    verbose: bool
    dry_run: bool
    replay_mode: ReplayMode
    replay_epoch: str
    exit_after_boot: bool
    verify_replay: bool
    fast_mode: bool


@dataclass(frozen=True)
class FacadeRuntimeState:
    """Derived runtime values that were historically implicit in env lookups."""

    dry_run_env: bool
    selected_epoch: str


def dry_run_env_enabled(env: Mapping[str, str]) -> bool:
    return env.get("ADAAD_DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}


def select_epoch(epoch: str, replay_epoch: str) -> str:
    return (epoch or replay_epoch).strip()


def resolve_replay_mode(value: str | bool | ReplayMode) -> ReplayMode:
    return normalize_replay_mode(value)


def build_init_state(*, args: object, dry_run_env: bool, replay_mode: ReplayMode, selected_epoch: str) -> OrchestratorInitState:
    return OrchestratorInitState(
        verbose=bool(getattr(args, "verbose")),
        dry_run=bool(getattr(args, "dry_run")) or dry_run_env,
        replay_mode=replay_mode,
        replay_epoch=selected_epoch,
        exit_after_boot=bool(getattr(args, "exit_after_boot")),
        verify_replay=bool(getattr(args, "verify_replay")),
        fast_mode=bool(getattr(args, "fast", False)),
    )
