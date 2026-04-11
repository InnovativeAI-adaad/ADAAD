# SPDX-License-Identifier: Apache-2.0
from pathlib import Path


def _dork_html() -> str:
    return Path("ui/dork.html").read_text(encoding="utf-8")


def test_dork_api_key_not_persisted_in_local_storage() -> None:
    html = _dork_html()
    assert "localStorage.getItem('dork_api_key')" not in html
    assert "localStorage.setItem('dork_api_key'" not in html


def test_dork_session_scoped_key_controls_present() -> None:
    html = _dork_html()
    assert 'id="cfg-remember-key"' in html
    assert "Remember key for this session" in html
    assert "sessionStorage.getItem(SESSION_KEY_STORAGE_KEY)" in html
    assert "sessionStorage.setItem(SESSION_KEY_STORAGE_KEY" in html
    assert "expiresAt: Date.now() + SESSION_KEY_TTL_MS" in html


def test_dork_clear_chat_and_clear_secrets_wipe_session_key() -> None:
    html = _dork_html()
    assert "function clearSecrets()" in html
    assert "sessionStorage.removeItem(SESSION_KEY_STORAGE_KEY);" in html
    assert "clearSecrets();" in html
    assert "q('#cfg-clear-secrets').addEventListener('click', clearSecrets);" in html
