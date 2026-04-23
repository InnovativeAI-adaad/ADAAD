# SPDX-License-Identifier: Apache-2.0
"""Factory helpers for constructing runtime orchestrator instances."""

from __future__ import annotations

from typing import TYPE_CHECKING

from adaad.orchestrator.boot_config import OrchestratorInitState

if TYPE_CHECKING:
    from adaad.main import Orchestrator


def build_orchestrator(init_state: OrchestratorInitState) -> "Orchestrator":
    from adaad.main import Orchestrator

    return Orchestrator(
        dry_run=init_state.dry_run,
        replay_mode=init_state.replay_mode,
        replay_epoch=init_state.replay_epoch,
        exit_after_boot=init_state.exit_after_boot,
        verbose=init_state.verbose,
        fast_mode=init_state.fast_mode,
    )
