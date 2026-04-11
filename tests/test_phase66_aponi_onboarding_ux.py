# SPDX-License-Identifier: Apache-2.0
"""
Phase 66 tests — Aponi guided onboarding UX.

Coverage:
- onboarding completion persistence
- shortcut discoverability
- starter prompt conversion flow
"""

from __future__ import annotations


def _read_aponi_html() -> str:
    with open("ui/aponi/index.html", encoding="utf-8") as handle:
        return handle.read()


def test_T66_U01_onboarding_completion_persistence_keys_present() -> None:
    html = _read_aponi_html()
    assert "aponi.onboarding.completed.v1" in html
    assert "aponi.onboarding.session.completed.v1" in html
    assert "completeOnboarding" in html


def test_T66_U02_shortcut_discoverability_contains_tour_shortcut() -> None:
    html = _read_aponi_html()
    assert "<kbd>T</kbd>" in html
    assert "Replay guided onboarding tour" in html
    assert 'id="btnKbdHelp"' in html


def test_T66_U03_starter_prompt_conversion_path_present() -> None:
    html = _read_aponi_html()
    assert "starterPromptsByRole" in html
    assert "[starter-prompt]" in html
    assert "Prompt conversions this session" in html
