from __future__ import annotations

from fastapi.testclient import TestClient

import server


def test_resolve_ui_paths_prefers_aponi(tmp_path, monkeypatch):
    root = tmp_path
    aponi = root / "ui" / "aponi"
    enhanced = root / "ui" / "enhanced"
    aponi.mkdir(parents=True)
    enhanced.mkdir(parents=True)
    (aponi / "index.html").write_text("aponi", encoding="utf-8")
    (enhanced / "enhanced_dashboard.html").write_text("enhanced", encoding="utf-8")

    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(server, "APONI_DIR", aponi)
    monkeypatch.setattr(server, "ENHANCED_DIR", enhanced)
    monkeypatch.setattr(server, "INDEX", aponi / "index.html")
    monkeypatch.setattr(server, "ENHANCED_INDEX", enhanced / "enhanced_dashboard.html")

    ui_dir, ui_index, mock_dir, ui_source = server._resolve_ui_paths(create_placeholder=False)

    assert ui_source == "aponi"
    assert ui_dir == aponi
    assert ui_index == aponi / "index.html"
    assert mock_dir == aponi / "mock"


def test_resolve_ui_paths_creates_placeholder_when_missing(tmp_path, monkeypatch):
    root = tmp_path
    aponi = root / "ui" / "aponi"
    enhanced = root / "ui" / "enhanced"

    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(server, "APONI_DIR", aponi)
    monkeypatch.setattr(server, "ENHANCED_DIR", enhanced)
    monkeypatch.setattr(server, "INDEX", aponi / "index.html")
    monkeypatch.setattr(server, "ENHANCED_INDEX", enhanced / "enhanced_dashboard.html")

    ui_dir, ui_index, mock_dir, ui_source = server._resolve_ui_paths(create_placeholder=True)

    assert ui_source == "placeholder"
    assert ui_dir == aponi
    assert ui_index == aponi / "index.html"
    assert ui_index.exists()
    assert "placeholder" in ui_index.read_text(encoding="utf-8").lower()
    assert mock_dir == aponi / "mock"


def test_current_ui_before_startup_returns_missing_without_creating_files(tmp_path, monkeypatch):
    root = tmp_path
    aponi = root / "ui" / "aponi"
    enhanced = root / "ui" / "enhanced"

    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(server, "APONI_DIR", aponi)
    monkeypatch.setattr(server, "ENHANCED_DIR", enhanced)
    monkeypatch.setattr(server, "INDEX", aponi / "index.html")
    monkeypatch.setattr(server, "ENHANCED_INDEX", enhanced / "enhanced_dashboard.html")

    for key in ("ui_dir", "ui_index", "mock_dir", "ui_source"):
        if hasattr(server.app.state, key):
            delattr(server.app.state, key)

    ui_dir, ui_index, _, ui_source = server._current_ui()

    assert ui_source == "missing"
    assert ui_dir == aponi
    assert ui_index == aponi / "index.html"
    assert not ui_index.exists()


def test_serve_dashboard_blocks_path_traversal(tmp_path, monkeypatch):
    root = tmp_path
    aponi = root / "ui" / "aponi"
    aponi.mkdir(parents=True)
    (aponi / "index.html").write_text("<html>ok</html>", encoding="utf-8")

    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(server, "APONI_DIR", aponi)
    monkeypatch.setattr(server, "ENHANCED_DIR", root / "ui" / "enhanced")
    monkeypatch.setattr(server, "INDEX", aponi / "index.html")
    monkeypatch.setattr(server, "ENHANCED_INDEX", root / "ui" / "enhanced" / "enhanced_dashboard.html")

    with TestClient(server.app) as client:
        response = client.get("/%2e%2e/%2e%2e/etc/passwd")

    assert response.status_code == 404
