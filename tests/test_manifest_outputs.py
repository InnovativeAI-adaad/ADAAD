# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from app.dream_mode import DreamMode
from app.main import Orchestrator


class _Fitness:
    def to_dict(self) -> dict:
        return {"score": 0.95, "constitution_ok": True}


def test_write_dream_manifest_creates_expected_file(tmp_path: Path) -> None:
    dream = DreamMode(tmp_path / "agents", tmp_path / "lineage", replay_mode="audit", recovery_tier="advisory")
    staged_path = tmp_path / "lineage" / "_staging" / "candidate"
    staged_path.mkdir(parents=True)

    manifest_path = dream.write_dream_manifest(
        agent_id="agent.alpha",
        epoch_id="epoch-42",
        bundle_id="dream",
        staged_path=staged_path,
        fitness=_Fitness(),
    )

    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["agent_id"] == "agent.alpha"
    assert payload["epoch_id"] == "epoch-42"
    assert payload["bundle_id"] == "dream"
    assert payload["staged_path"] == str(staged_path)
    assert payload["replay_mode"] == "audit"
    assert payload["recovery_tier"] == "advisory"
    assert payload["fitness"]["score"] == 0.95


def test_write_replay_manifest_creates_expected_file() -> None:
    orchestrator = object.__new__(Orchestrator)
    outcome = {
        "mode": "strict",
        "verify_only": False,
        "ok": True,
        "decision": "match",
        "target": "epoch:2026-02-13T10:00:00Z",
        "divergence": False,
        "results": [{"expected": "sha256:abc", "actual": "sha256:abc"}],
        "ts": "2026-02-13T10:00:00Z",
    }

    manifest_path = orchestrator.write_replay_manifest(outcome)

    assert Path(manifest_path).exists()
    assert Path(manifest_path).parent.name == "replay_manifests"
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    assert payload["mode"] == "strict"
    assert payload["target"] == "epoch:2026-02-13T10:00:00Z"
    assert payload["decision"] == "match"
    assert payload["ok"] is True

    Path(manifest_path).unlink(missing_ok=True)
