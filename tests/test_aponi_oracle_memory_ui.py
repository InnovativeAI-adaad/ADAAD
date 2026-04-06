# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path


def test_aponi_oracle_memory_summary_and_timeline_deeplink_present() -> None:
    js = Path("ui/aponi/innovations_panel.js").read_text(encoding="utf-8")
    assert "/innovations/oracle/memory?limit=10" in js
    assert "Since last 10 Oracle calls" in js
    assert "→ Dork follow-up" in js
