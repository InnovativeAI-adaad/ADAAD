from __future__ import annotations

import tempfile
from pathlib import Path

from adaad.core.cryovant import build_identity, deterministic_source_hash
from runtime import capability_graph


def test_deterministic_source_hash_normalizes_line_endings(tmp_path: Path) -> None:
    source = tmp_path / "tool.py"
    source.write_text("def run():\r\n    return 1\r\n", encoding="utf-8")
    normalized = tmp_path / "tool_normalized.py"
    normalized.write_text("def run():\n    return 1\n", encoding="utf-8")

    assert deterministic_source_hash(source) == deterministic_source_hash(normalized)


def test_build_identity_contains_required_fields() -> None:
    identity = build_identity("runtime.manifest.generator", "tool.alpha", "1.2.3")
    assert identity["tool_id"] == "tool.alpha"
    assert identity["version"] == "1.2.3"
    assert len(identity["hash"]) == 64


def test_registration_and_dispatch_require_identity_fields() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_capabilities_path = capability_graph.CAPABILITIES_PATH
        capability_graph.CAPABILITIES_PATH = Path(tmp_dir) / "capabilities.json"
        try:
            ok, message = capability_graph.register_capability("tool.noid", "1.0.0", 0.5, "test")
            assert ok is False
            assert "identity" in message

            identity = build_identity("runtime.manifest.generator", "tool.withid", "1.0.0")
            identity["timestamp"] = "2026-01-01T00:00:00Z"
            ok, _ = capability_graph.register_capability("tool.withid", "1.0.0", 0.8, "test", identity=identity)
            assert ok is True

            dispatched_ok, status, entry = capability_graph.dispatch_capability("tool.withid")
            assert dispatched_ok is True
            assert status == "ok"
            assert entry is not None

            listing = capability_graph.list_capabilities()
            assert listing[0]["version"] == "1.0.0"
            assert listing[0]["tool_id"] == "tool.withid"
            assert listing[0]["identity_hash"] == identity["hash"]
        finally:
            capability_graph.CAPABILITIES_PATH = original_capabilities_path
