# SPDX-License-Identifier: Apache-2.0
"""Phase 13 / Track 11-B — market_signal_integrity_invariant (PR-13-B-02).

Tests verify:
  T13-B-09  CONSTITUTION_VERSION is "0.7.0"
  T13-B-10  constitution.yaml has market_signal_integrity_invariant rule enabled + blocking
  T13-B-11  validator passes when chain absent (advisory pass)
  T13-B-12  validator passes when consecutive_synthetic_epochs == 0
  T13-B-13  validator passes when consecutive_synthetic_epochs <= MAX (5)
  T13-B-14  validator fails (ok=False) when consecutive_synthetic_epochs > MAX
  T13-B-15  ADAAD_MARKET_MAX_SYNTHETIC_EPOCHS env override is respected
  T13-B-16  violation reason string indicates cap exceeded
  T13-B-17  validator passes advisory when chain is unreadable
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
pytestmark = pytest.mark.governance_gate

from runtime.constitution import CONSTITUTION_VERSION


# ---------------------------------------------------------------------------
# T13-B-09: Constitution version
# ---------------------------------------------------------------------------

class TestConstitutionVersion:
    def test_constitution_version_is_0_7_0(self):
        assert CONSTITUTION_VERSION == "1.0.0"


# ---------------------------------------------------------------------------
# T13-B-10: constitution.yaml rule present + configuration
# ---------------------------------------------------------------------------

class TestConstitutionYamlRule:
    def _load_yaml(self) -> dict:
        path = Path("runtime/governance/constitution.yaml")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_rule_exists_in_yaml(self):
        doc = self._load_yaml()
        names = [r["name"] for r in doc["rules"]]
        assert "market_signal_integrity_invariant" in names

    def test_rule_is_enabled(self):
        doc = self._load_yaml()
        rule = next(r for r in doc["rules"] if r["name"] == "market_signal_integrity_invariant")
        assert rule["enabled"] is True

    def test_rule_severity_is_blocking(self):
        doc = self._load_yaml()
        rule = next(r for r in doc["rules"] if r["name"] == "market_signal_integrity_invariant")
        assert rule["severity"] == "blocking"

    def test_rule_sandbox_override_is_warning(self):
        doc = self._load_yaml()
        rule = next(r for r in doc["rules"] if r["name"] == "market_signal_integrity_invariant")
        assert rule["tier_overrides"]["SANDBOX"] == "warning"

    def test_rule_max_synthetic_epochs_is_5(self):
        doc = self._load_yaml()
        rule = next(r for r in doc["rules"] if r["name"] == "market_signal_integrity_invariant")
        assert rule["max_synthetic_epochs"] == 5

    def test_rule_env_override_key(self):
        doc = self._load_yaml()
        rule = next(r for r in doc["rules"] if r["name"] == "market_signal_integrity_invariant")
        assert rule["env_override"] == "ADAAD_MARKET_MAX_SYNTHETIC_EPOCHS"

    def test_constitution_yaml_version_is_0_7_0(self):
        doc = self._load_yaml()
        assert doc["version"] == "1.0.0"


# ---------------------------------------------------------------------------
# Helpers for validator tests
# ---------------------------------------------------------------------------

def _write_chain(tmp_path: Path, consecutive: int) -> Path:
    """Write a minimal checkpoint chain JSON Lines file with the given counter."""
    entry = {"payload": {"consecutive_synthetic_market_epochs": consecutive}}
    chain = tmp_path / "checkpoint_chain.jsonl"
    chain.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    return chain


def _run_validator(chain_path: str | None = None, max_synthetic: str | None = None):
    from runtime.constitution import VALIDATOR_REGISTRY
    from unittest.mock import MagicMock

    validator_fn = VALIDATOR_REGISTRY["market_signal_integrity_invariant"]
    req = MagicMock()  # validator ignores the request object

    env_overrides: dict = {}
    if chain_path is not None:
        env_overrides["ADAAD_CHAIN_PATH"] = chain_path
    if max_synthetic is not None:
        env_overrides["ADAAD_MARKET_MAX_SYNTHETIC_EPOCHS"] = max_synthetic

    # Remove any existing env vars that would interfere
    clean_env = {
        k: v for k, v in os.environ.items()
        if k not in ("ADAAD_CHAIN_PATH", "ADAAD_MARKET_MAX_SYNTHETIC_EPOCHS")
    }
    clean_env.update(env_overrides)

    with patch.dict(os.environ, clean_env, clear=True):
        return validator_fn(req)


# ---------------------------------------------------------------------------
# T13-B-11: Advisory pass when chain absent
# ---------------------------------------------------------------------------

class TestValidatorChainAbsent:
    def test_passes_when_no_chain_file(self, tmp_path):
        result = _run_validator(chain_path=str(tmp_path / "nonexistent.jsonl"))
        assert result["ok"] is True
        assert "absent" in result["reason"] or "advisory" in result["reason"]

    def test_passes_when_chain_is_empty(self, tmp_path):
        chain = tmp_path / "empty.jsonl"
        chain.write_text("", encoding="utf-8")
        result = _run_validator(chain_path=str(chain))
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# T13-B-12/13: Passes when counter == 0 or within cap
# ---------------------------------------------------------------------------

class TestValidatorWithinCap:
    def test_passes_when_counter_is_zero(self, tmp_path):
        chain = _write_chain(tmp_path, consecutive=0)
        result = _run_validator(chain_path=str(chain))
        assert result["ok"] is True

    def test_passes_when_counter_equals_max(self, tmp_path):
        chain = _write_chain(tmp_path, consecutive=5)
        result = _run_validator(chain_path=str(chain))
        assert result["ok"] is True

    def test_passes_when_counter_is_below_max(self, tmp_path):
        chain = _write_chain(tmp_path, consecutive=3)
        result = _run_validator(chain_path=str(chain))
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# T13-B-14: Fails when cap exceeded
# ---------------------------------------------------------------------------

class TestValidatorCapExceeded:
    def test_fails_when_counter_exceeds_default_max(self, tmp_path):
        chain = _write_chain(tmp_path, consecutive=6)
        result = _run_validator(chain_path=str(chain))
        assert result["ok"] is False

    def test_fails_when_counter_is_well_above_max(self, tmp_path):
        chain = _write_chain(tmp_path, consecutive=20)
        result = _run_validator(chain_path=str(chain))
        assert result["ok"] is False

    def test_details_cap_exceeded_true(self, tmp_path):
        chain = _write_chain(tmp_path, consecutive=6)
        result = _run_validator(chain_path=str(chain))
        assert result["details"]["cap_exceeded"] is True

    def test_details_consecutive_count_correct(self, tmp_path):
        chain = _write_chain(tmp_path, consecutive=8)
        result = _run_validator(chain_path=str(chain))
        assert result["details"]["consecutive_synthetic_epochs"] == 8


# ---------------------------------------------------------------------------
# T13-B-15: Env override respected
# ---------------------------------------------------------------------------

class TestEnvOverride:
    def test_passes_with_larger_env_override(self, tmp_path):
        chain = _write_chain(tmp_path, consecutive=8)
        result = _run_validator(chain_path=str(chain), max_synthetic="10")
        assert result["ok"] is True

    def test_fails_with_smaller_env_override(self, tmp_path):
        chain = _write_chain(tmp_path, consecutive=3)
        result = _run_validator(chain_path=str(chain), max_synthetic="2")
        assert result["ok"] is False

    def test_override_reflected_in_details(self, tmp_path):
        chain = _write_chain(tmp_path, consecutive=1)
        result = _run_validator(chain_path=str(chain), max_synthetic="7")
        assert result["details"]["max_synthetic_epochs"] == 7


# ---------------------------------------------------------------------------
# T13-B-16: Violation reason string
# ---------------------------------------------------------------------------

class TestViolationReason:
    def test_violation_reason_mentions_cap_exceeded(self, tmp_path):
        chain = _write_chain(tmp_path, consecutive=6)
        result = _run_validator(chain_path=str(chain))
        assert "cap_exceeded" in result["reason"] or "violation" in result["reason"]


# ---------------------------------------------------------------------------
# T13-B-17: Advisory pass on unreadable chain
# ---------------------------------------------------------------------------

class TestUnreadableChain:
    def test_passes_advisory_on_malformed_chain(self, tmp_path):
        chain = tmp_path / "bad.jsonl"
        chain.write_text("{not valid json\n", encoding="utf-8")
        result = _run_validator(chain_path=str(chain))
        assert result["ok"] is True
