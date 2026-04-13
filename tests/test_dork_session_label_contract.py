# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _session_label_js_block(html: str) -> str:
    match = re.search(
        r"const DORK_SESSION_LABEL_KEY = 'dork_session_label';[\s\S]*?function getOrCreateSessionLabel\(epochId\) \{[\s\S]*?\n\}",
        html,
    )
    assert match, "expected session-label helper block in ui/dork.html"
    return match.group(0)


def _run_node_assertions(js_block: str) -> None:
    script = f"""
{js_block}

function makeStorage(seed) {{
  const backing = new Map(Object.entries(seed || {{}}));
  return {{
    getItem: (k) => backing.has(k) ? backing.get(k) : null,
    setItem: (k, v) => backing.set(k, String(v)),
    removeItem: (k) => backing.delete(k),
    dump: () => Object.fromEntries(backing.entries()),
  }};
}}

function assert(condition, msg) {{
  if (!condition) throw new Error(msg);
}}

// Reload case: same session storage should preserve exact label.
globalThis.Date = {{ now: () => 1700000000000 }};
globalThis.sessionStorage = makeStorage();
const first = getOrCreateSessionLabel('epoch-42');
const second = getOrCreateSessionLabel('epoch-99');
assert(first === second, 'label must be stable for the same session lifecycle');
assert(/^dork_ep-[a-z0-9-]+_s-[a-z0-9]+$/.test(first), 'label must follow compact format');

// New label in same tab lifecycle (label key cleared) increments monotonic counter.
sessionStorage.removeItem('dork_session_label');
const third = getOrCreateSessionLabel('epoch-77');
assert(third.endsWith('_s-2'), 'counter should increment monotonically when regenerating a label');

// New browser session (fresh sessionStorage) starts clean.
globalThis.sessionStorage = makeStorage();
const fresh = getOrCreateSessionLabel('epoch-42');
assert(fresh.endsWith('_s-1'), 'new session should begin with counter 1');
"""
    subprocess.run(["node", "-e", script], check=True)


def test_dork_session_label_generation_is_deterministic_and_compact() -> None:
    html = Path("ui/dork.html").read_text(encoding="utf-8")
    _run_node_assertions(_session_label_js_block(html))


def test_dork_session_label_no_math_random_and_display_only_contract_note() -> None:
    html = Path("ui/dork.html").read_text(encoding="utf-8")
    assert "Math.random().toString(36).slice(2, 10)" not in html
    assert "Display-only identifier for UI observability; never used for auth/crypto decisions." in html
