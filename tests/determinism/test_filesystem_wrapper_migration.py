from __future__ import annotations

import json
from pathlib import Path

from runtime.evolution.replay_attestation import load_replay_proof
from runtime.evolution.simulation_runner import _load_candidate
from runtime.governance.deterministic_envelope import ENTROPY_COSTS, EntropySource, deterministic_envelope
from runtime.governance.deterministic_filesystem import (
    find_files_deterministic,
    glob_deterministic,
    listdir_deterministic,
    read_file_deterministic,
    walk_deterministic,
)
from runtime.governance.gate_certifier import GateCertifier
from runtime.governance.schema_validator import validate_governance_schemas


def test_deterministic_filesystem_helpers_are_stably_sorted_and_charge_entropy(tmp_path: Path) -> None:
    (tmp_path / "z-dir").mkdir()
    (tmp_path / "a-dir").mkdir()
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "z-dir" / "c.txt").write_text("c", encoding="utf-8")

    with deterministic_envelope("fs-order", budget=100) as ledger:
        listed = listdir_deterministic(tmp_path)
        walked = list(walk_deterministic(tmp_path))
        globbed = glob_deterministic(str(tmp_path / "*.txt"))
        found = find_files_deterministic(tmp_path, pattern="*.txt")

    assert listed == ["a-dir", "a.txt", "b.txt", "z-dir"]
    assert walked[0][1] == ["a-dir", "z-dir"]
    assert walked[0][2] == ["a.txt", "b.txt"]
    assert globbed == [str(tmp_path / "a.txt"), str(tmp_path / "b.txt")]
    assert found == [str(tmp_path / "a.txt"), str(tmp_path / "b.txt"), str(tmp_path / "z-dir" / "c.txt")]
    assert ledger.consumed == ENTROPY_COSTS[EntropySource.FILESYSTEM] * 4


def test_read_file_deterministic_charges_entropy_per_read(tmp_path: Path) -> None:
    target = tmp_path / "payload.json"
    target.write_text('{"ok": true}', encoding="utf-8")

    with deterministic_envelope("fs-read", budget=100) as ledger:
        assert read_file_deterministic(target) == '{"ok": true}'
        assert read_file_deterministic(target) == '{"ok": true}'

    assert ledger.consumed == ENTROPY_COSTS[EntropySource.FILESYSTEM] * 2


def test_migrated_callsites_charge_filesystem_entropy(tmp_path: Path) -> None:
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps({"candidate_id": "cand-1"}), encoding="utf-8")
    proof_path = tmp_path / "proof.json"
    proof_path.write_text(json.dumps({"proof_id": "proof-1"}), encoding="utf-8")
    source_path = tmp_path / "target.py"
    source_path.write_text("print('ok')\n", encoding="utf-8")

    with deterministic_envelope("migrated-callsite", budget=100) as ledger:
        assert _load_candidate(candidate_path) == {"candidate_id": "cand-1"}
        assert load_replay_proof(proof_path) == {"proof_id": "proof-1"}
        result = GateCertifier().certify(source_path, {"cryovant_token": "invalid"})
        assert result["checks"]["token_ok"] is True
        assert validate_governance_schemas([Path("schemas/replay_attestation.v1.json")]) == {}

    assert ledger.consumed >= ENTROPY_COSTS[EntropySource.FILESYSTEM] * 4
