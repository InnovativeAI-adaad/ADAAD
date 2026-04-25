# SPDX-License-Identifier: Apache-2.0

import os

import pytest

from tools import lint_determinism


pytestmark = [
    pytest.mark.regression_standard,
    pytest.mark.qa7,
    pytest.mark.dev_only,
]

QA7_LINT_ROLLOUT_ENABLED = os.getenv("QA7_LINT_ROLLOUT", "").lower() in {"1", "true", "yes", "on"}
qa7_gate = pytest.mark.skipif(
    not QA7_LINT_ROLLOUT_ENABLED,
    reason=(
        "QA-7 rollout tests require explicit opt-in lane selection "
        "(set QA7_LINT_ROLLOUT=1 and run pytest -m qa7 tests/rollout -q)."
    ),
)


@qa7_gate
def test_lint_targets_include_selected_replay_sensitive_app_modules() -> None:
    targets = set(lint_determinism.TARGET_FILES)
    assert "app/dream_mode.py" in targets
    assert "app/beast_mode_loop.py" in targets
