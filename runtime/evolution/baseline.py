# SPDX-License-Identifier: Apache-2.0
"""Baseline schema and append-only storage for replay trust decisions."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from runtime import ROOT_DIR
from runtime.constitution import CONSTITUTION_VERSION, POLICY_HASH
from runtime.timeutils import now_iso

BASELINE_LEDGER_PATH = ROOT_DIR / "security" / "ledger" / "baselines.jsonl"


@dataclass(frozen=True)
class BaselineRecord:
    baseline_id: str
    epoch_id: str
    created_ts: str
    provider_id: str
    model_id: str
    prompt_pack_version: str
    prompt_pack_hash: str
    mutation_sampling_config: Dict[str, Any]
    constitution_version: str
    constitution_hash: str
    replay_mode: str
    recovery_tier: str
    baseline_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "baseline_id": self.baseline_id,
            "epoch_id": self.epoch_id,
            "created_ts": self.created_ts,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "prompt_pack_version": self.prompt_pack_version,
            "prompt_pack_hash": self.prompt_pack_hash,
            "mutation_sampling_config": self.mutation_sampling_config,
            "constitution_version": self.constitution_version,
            "constitution_hash": self.constitution_hash,
            "replay_mode": self.replay_mode,
            "recovery_tier": self.recovery_tier,
            "baseline_hash": self.baseline_hash,
        }


def _compute_hash(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _mutation_sampling_from_env() -> Dict[str, Any]:
    return {
        "strategy": os.getenv("ADAAD_MUTATION_SAMPLING_STRATEGY", "default"),
        "sample_size": int(os.getenv("ADAAD_MUTATION_SAMPLE_SIZE", "1")),
        "temperature": float(os.getenv("ADAAD_MUTATION_TEMPERATURE", "0.0")),
        "top_p": float(os.getenv("ADAAD_MUTATION_TOP_P", "1.0")),
    }


def create_baseline(*, epoch_id: str, replay_mode: str, recovery_tier: str) -> BaselineRecord:
    baseline_id = f"baseline-{uuid.uuid4().hex[:12]}"
    material = {
        "baseline_id": baseline_id,
        "epoch_id": epoch_id,
        "created_ts": now_iso(),
        "provider_id": os.getenv("ADAAD_PROVIDER_ID", "unknown_provider"),
        "model_id": os.getenv("ADAAD_MODEL_ID", "unknown_model"),
        "prompt_pack_version": os.getenv("ADAAD_PROMPT_PACK_VERSION", "unknown_prompt_pack"),
        "prompt_pack_hash": os.getenv("ADAAD_PROMPT_PACK_HASH", "sha256:unknown"),
        "mutation_sampling_config": _mutation_sampling_from_env(),
        "constitution_version": CONSTITUTION_VERSION,
        "constitution_hash": POLICY_HASH,
        "replay_mode": replay_mode,
        "recovery_tier": recovery_tier,
    }
    baseline_hash = _compute_hash(material)
    return BaselineRecord(**material, baseline_hash=baseline_hash)


class BaselineStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or BASELINE_LEDGER_PATH

    def append(self, baseline: BaselineRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(baseline.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")

    def find_for_epoch(self, epoch_id: str) -> Dict[str, Any] | None:
        if not self.path.exists():
            return None
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                row = line.strip()
                if not row:
                    continue
                try:
                    entry = json.loads(row)
                except json.JSONDecodeError:
                    continue
                if str(entry.get("epoch_id") or "") == epoch_id:
                    return entry
        return None


__all__ = ["BaselineRecord", "BaselineStore", "BASELINE_LEDGER_PATH", "create_baseline"]
