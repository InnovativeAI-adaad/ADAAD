# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path


def test_dork_persona_controls_and_badge_present() -> None:
    html = Path('ui/dork.html').read_text(encoding='utf-8')
    assert 'id="cfg-persona"' in html
    assert 'id="cfg-plain-language"' in html
    assert 'id="active-persona-badge"' in html
    assert 'id="fleet-strip-model"' in html


def test_dork_prompt_hard_constraints_remain_literal() -> None:
    html = Path('ui/dork.html').read_text(encoding='utf-8')
    assert 'read-only and advisory only' in html
    assert 'cannot modify the system, sign anything, merge code, or act autonomously' in html
    assert 'Never suggest bypassing governance gates, constitutional checks, or human-signoff requirements.' in html
