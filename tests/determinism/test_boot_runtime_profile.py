import pytest
pytestmark = pytest.mark.autonomous_critical
# SPDX-License-Identifier: Apache-2.0

import json

from runtime import ROOT_DIR
from runtime.preflight import validate_boot_runtime_profile


def _write_profile(profile: dict) -> None:
    (ROOT_DIR / "governance_runtime_profile.lock.json").write_text(
        json.dumps(profile, indent=2) + "\n", encoding="utf-8"
    )


def _patch_fingerprint_ok(monkeypatch) -> None:
    """Patch _dependency_fingerprint to return the locked value so fingerprint
    check always passes and tests can exercise downstream logic."""
    import runtime.preflight as _pf
    profile = json.loads((ROOT_DIR / "governance_runtime_profile.lock.json").read_text(encoding="utf-8"))
    expected = str(profile.get("dependency_lock", {}).get("sha256", ""))
    monkeypatch.setattr(_pf, "_dependency_fingerprint", lambda _path: expected)


def test_boot_profile_fails_closed_on_dependency_fingerprint_mismatch(monkeypatch) -> None:
    profile_path = ROOT_DIR / "governance_runtime_profile.lock.json"
    original = profile_path.read_text(encoding="utf-8")
    profile = json.loads(original)
    profile["dependency_lock"]["sha256"] = "0" * 64
    try:
        _write_profile(profile)
        monkeypatch.setenv("ADAAD_FORCE_DETERMINISTIC_PROVIDER", "1")
        monkeypatch.setenv("ADAAD_DISABLE_MUTABLE_FS", "1")
        monkeypatch.setenv("ADAAD_DISABLE_NETWORK", "1")
        result = validate_boot_runtime_profile(replay_mode="strict")
        assert result["ok"] is False
        assert result["reason"] == "dependency_fingerprint_mismatch"
    finally:
        profile_path.write_text(original, encoding="utf-8")


def test_boot_profile_fails_closed_on_non_hermetic_surface(monkeypatch) -> None:
    # Patch fingerprint so we reach the surface check, not the fingerprint check.
    _patch_fingerprint_ok(monkeypatch)
    monkeypatch.setenv("ADAAD_FORCE_DETERMINISTIC_PROVIDER", "1")
    monkeypatch.delenv("ADAAD_DISABLE_MUTABLE_FS", raising=False)
    monkeypatch.setenv("ADAAD_MUTABLE_FS_ALLOWLIST", "reports,/tmp")
    monkeypatch.setenv("ADAAD_DISABLE_NETWORK", "1")

    result = validate_boot_runtime_profile(replay_mode="strict")

    assert result["ok"] is False
    assert result["reason"] == "mutable_filesystem_surface_must_be_disabled_or_allowlisted"


def test_boot_profile_passes_with_deterministic_provider_and_disabled_surfaces(monkeypatch) -> None:
    _patch_fingerprint_ok(monkeypatch)
    monkeypatch.setenv("ADAAD_FORCE_DETERMINISTIC_PROVIDER", "1")
    monkeypatch.setenv("ADAAD_DISABLE_MUTABLE_FS", "1")
    monkeypatch.setenv("ADAAD_DISABLE_NETWORK", "1")

    result = validate_boot_runtime_profile(replay_mode="audit")

    assert result["ok"] is True
    assert result["checks"]["deterministic_provider"]["ok"] is True
    assert result["checks"]["mutable_filesystem"]["status"] == "disabled"
    assert result["checks"]["network"]["status"] == "disabled"


def test_boot_profile_backward_compatible_when_agents_section_missing(monkeypatch) -> None:
    profile_path = ROOT_DIR / "governance_runtime_profile.lock.json"
    original = profile_path.read_text(encoding="utf-8")
    profile = json.loads(original)
    profile.pop("agents", None)
    try:
        _write_profile(profile)
        _patch_fingerprint_ok(monkeypatch)
        monkeypatch.setenv("ADAAD_FORCE_DETERMINISTIC_PROVIDER", "1")
        monkeypatch.setenv("ADAAD_DISABLE_MUTABLE_FS", "1")
        monkeypatch.setenv("ADAAD_DISABLE_NETWORK", "1")

        result = validate_boot_runtime_profile(replay_mode="strict")

        assert result["ok"] is True
        assert "added_agents_section" in result["checks"]["profile_migration"]
        assert "added_agents.grok-integrator" in result["checks"]["profile_migration"]
    finally:
        profile_path.write_text(original, encoding="utf-8")


def test_boot_profile_fails_closed_on_invalid_agents_section(monkeypatch) -> None:
    profile_path = ROOT_DIR / "governance_runtime_profile.lock.json"
    original = profile_path.read_text(encoding="utf-8")
    profile = json.loads(original)
    profile["agents"] = {"grok-integrator": {"enabled": "false"}}
    try:
        _write_profile(profile)
        _patch_fingerprint_ok(monkeypatch)
        monkeypatch.setenv("ADAAD_FORCE_DETERMINISTIC_PROVIDER", "1")
        monkeypatch.setenv("ADAAD_DISABLE_MUTABLE_FS", "1")
        monkeypatch.setenv("ADAAD_DISABLE_NETWORK", "1")

        result = validate_boot_runtime_profile(replay_mode="strict")

        assert result["ok"] is False
        assert result["reason"] == "runtime_profile_schema_invalid"
    finally:
        profile_path.write_text(original, encoding="utf-8")
