from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from runtime.mutation_lifecycle import (
    LifecycleTransitionError,
    MutationLifecycleContext,
    retry_transition,
    rollback,
    transition,
)


def _context(**overrides):
    base = MutationLifecycleContext(
        mutation_id="m-1",
        agent_id="sample",
        epoch_id="epoch-1",
        signature="cryovant-dev-seed",
        trust_mode="dev",
        founders_law_result=(True, []),
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


@mock.patch("runtime.mutation_lifecycle.journal.append_tx")
@mock.patch("runtime.mutation_lifecycle.journal.write_entry")
def test_rejects_undeclared_transition(write_entry, append_tx) -> None:
    context = _context()
    with pytest.raises(LifecycleTransitionError, match="undeclared_transition"):
        transition("proposed", "executing", context)
    assert write_entry.called
    assert append_tx.called


@mock.patch("runtime.mutation_lifecycle.journal.append_tx")
@mock.patch("runtime.mutation_lifecycle.journal.write_entry")
def test_requires_fitness_for_certified_to_executing(write_entry, append_tx) -> None:
    context = _context(cert_refs={"bundle_id": "b-1"}, fitness_score=0.1, fitness_threshold=0.5)
    with pytest.raises(LifecycleTransitionError, match="guard_failed"):
        transition("certified", "executing", context)
    assert write_entry.called
    assert append_tx.called


@mock.patch("runtime.mutation_lifecycle.journal.append_tx")
@mock.patch("runtime.mutation_lifecycle.journal.write_entry")
@mock.patch("runtime.mutation_lifecycle.cryovant.dev_signature_allowed", return_value=True)
def test_allows_declared_transition_with_guards(_dev_sig, write_entry, append_tx) -> None:
    context = _context(cert_refs={"bundle_id": "b-1"}, fitness_score=0.9)
    next_state = transition("certified", "executing", context)
    assert next_state == "executing"
    assert "executing" in context.stage_timestamps
    assert write_entry.called
    assert append_tx.called


@mock.patch("runtime.mutation_lifecycle.journal.append_tx")
@mock.patch("runtime.mutation_lifecycle.journal.write_entry")
@mock.patch("runtime.mutation_lifecycle.cryovant.dev_signature_allowed", return_value=True)
def test_founders_law_check_is_cached_across_transitions(_dev_sig, _write_entry, _append_tx) -> None:
    calls = []

    def _check():
        calls.append("called")
        return True, []

    context = _context(cert_refs={"bundle_id": "b-1"}, fitness_score=0.9, founders_law_result=None, founders_law_check=_check)
    assert transition("certified", "executing", context) == "executing"
    assert transition("executing", "completed", context) == "completed"
    assert calls == ["called"]


@mock.patch("runtime.mutation_lifecycle.journal.append_tx")
@mock.patch("runtime.mutation_lifecycle.journal.write_entry")
@mock.patch("runtime.mutation_lifecycle.cryovant.dev_signature_allowed", return_value=True)
def test_lifecycle_state_persist_and_restore(_dev_sig, _write_entry, _append_tx, tmp_path: Path) -> None:
    context = _context(cert_refs={"bundle_id": "b-1"}, fitness_score=0.9, state_dir=tmp_path)
    assert transition("certified", "executing", context) == "executing"
    restored = MutationLifecycleContext.restore("m-1", state_dir=tmp_path)
    assert restored is not None
    assert restored.current_state == "executing"


@mock.patch("runtime.mutation_lifecycle.journal.append_tx")
@mock.patch("runtime.mutation_lifecycle.journal.write_entry")
def test_rollback_supports_allowed_paths(_write_entry, _append_tx) -> None:
    context = _context(current_state="executing")
    assert rollback(context, "certified") == "certified"


@mock.patch("runtime.mutation_lifecycle.journal.append_tx")
@mock.patch("runtime.mutation_lifecycle.journal.write_entry")
def test_retry_transition_retries_until_success(_write_entry, _append_tx) -> None:
    context = _context(current_state="proposed")
    calls = {"count": 0}

    def _side_effect(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] < 2:
            raise LifecycleTransitionError("guard_failed:proposed->staged")
        return "staged"

    with mock.patch("runtime.mutation_lifecycle.transition", side_effect=_side_effect):
        out = retry_transition(context, "staged", max_attempts=2, sleep_fn=lambda _x: None)
    assert out == "staged"
