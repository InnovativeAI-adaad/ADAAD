# SPDX-License-Identifier: Apache-2.0

import hashlib
import json

from app.agents.mutation_request import MutationRequest
from runtime import constitution


def _request(agent_id: str = "test_subject") -> MutationRequest:
    return MutationRequest(
        agent_id=agent_id,
        generation_ts="now",
        intent="test",
        ops=[],
        signature="",
        nonce="n",
    )


def _with_hash(prev_hash: str, entry: dict) -> dict:
    payload = dict(entry)
    payload["prev_hash"] = prev_hash
    material = prev_hash + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["hash"] = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return payload


def test_contract_governance_envelope_has_digest_and_components() -> None:
    verdict = constitution.evaluate_mutation(_request(), constitution.Tier.SANDBOX)
    assert verdict["governance_envelope"]["digest"]
    components = verdict["governance_fingerprint_components"]
    assert components["constitution_version"] == constitution.CONSTITUTION_VERSION
    assert components["policy_hash"] == constitution.POLICY_HASH


def test_contract_drift_warns_in_sandbox(monkeypatch) -> None:
    monkeypatch.setattr(constitution, "_current_governance_fingerprint", lambda: "drifted")
    monkeypatch.setattr(constitution, "_BASE_GOVERNANCE_FINGERPRINT", "baseline")
    verdict = constitution.evaluate_mutation(_request(), constitution.Tier.SANDBOX)
    assert verdict["governance_drift_detected"] is True
    assert "governance_drift_detected" in verdict["warnings"]
    assert "governance_drift_detected" not in verdict["blocking_failures"]
    assert verdict["passed"] is True


def test_contract_validator_versions_are_emitted() -> None:
    verdict = constitution.evaluate_mutation(_request(), constitution.Tier.SANDBOX)
    row = next(item for item in verdict["verdicts"] if item["rule"] == "lineage_continuity")
    assert row["provenance"]["validator_version"]


def test_contract_lineage_cache_reuses_prior_result(monkeypatch, tmp_path) -> None:
    genesis = tmp_path / "genesis.jsonl"
    journal_path = tmp_path / "journal.jsonl"
    g = _with_hash("0" * 64, {"type": "Genesis", "payload": {"epoch_id": "ep"}})
    j = _with_hash(g["hash"], {"type": "Mutation", "payload": {"epoch_id": "ep"}})
    genesis.write_text(json.dumps(g, ensure_ascii=False) + "\n", encoding="utf-8")
    journal_path.write_text(json.dumps(j, ensure_ascii=False) + "\n", encoding="utf-8")

    monkeypatch.setattr(constitution.journal, "GENESIS_PATH", genesis)
    monkeypatch.setattr(constitution.journal, "JOURNAL_PATH", journal_path)
    constitution._LINEAGE_VALIDATION_CACHE.clear()

    first = constitution.VALIDATOR_REGISTRY["lineage_continuity"](_request())
    second = constitution.VALIDATOR_REGISTRY["lineage_continuity"](_request())
    assert first == second
