# SPDX-License-Identifier: Apache-2.0
"""Sandbox manifest model and deterministic validation helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Tuple


@dataclass(frozen=True)
class SandboxManifest:
    mutation_id: str
    epoch_id: str
    replay_seed: str
    command: Tuple[str, ...]
    env: Tuple[Tuple[str, str], ...]
    mounts: Tuple[str, ...]
    allowed_write_paths: Tuple[str, ...]
    allowed_network_hosts: Tuple[str, ...]
    cpu_seconds: int
    memory_mb: int
    disk_mb: int
    timeout_s: int
    deterministic_clock: bool
    deterministic_random: bool

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["env"] = [{"name": k, "value": v} for k, v in self.env]
        return payload


def validate_manifest(manifest: SandboxManifest) -> None:
    if not manifest.mutation_id or not manifest.epoch_id:
        raise ValueError("invalid_manifest_identity")
    if len(manifest.replay_seed) != 16:
        raise ValueError("invalid_replay_seed_length")
    if manifest.replay_seed.lower() == "0" * 16:
        raise ValueError("invalid_replay_seed_zero")
    int(manifest.timeout_s)
    int(manifest.memory_mb)
    int(manifest.cpu_seconds)
    int(manifest.disk_mb)
    if manifest.timeout_s <= 0 or manifest.memory_mb <= 0 or manifest.cpu_seconds <= 0 or manifest.disk_mb <= 0:
        raise ValueError("invalid_manifest_resource_bounds")


def manifest_from_mapping(raw: Mapping[str, Any]) -> SandboxManifest:
    env_items = tuple((str(item.get("name", "")), str(item.get("value", ""))) for item in (raw.get("env") or []))
    return SandboxManifest(
        mutation_id=str(raw.get("mutation_id") or ""),
        epoch_id=str(raw.get("epoch_id") or ""),
        replay_seed=str(raw.get("replay_seed") or ""),
        command=tuple(str(x) for x in (raw.get("command") or [])),
        env=tuple(sorted(env_items)),
        mounts=tuple(sorted(str(x) for x in (raw.get("mounts") or []))),
        allowed_write_paths=tuple(sorted(str(x) for x in (raw.get("allowed_write_paths") or []))),
        allowed_network_hosts=tuple(sorted(str(x) for x in (raw.get("allowed_network_hosts") or []))),
        cpu_seconds=int(raw.get("cpu_seconds", 1) or 1),
        memory_mb=int(raw.get("memory_mb", 1) or 1),
        disk_mb=int(raw.get("disk_mb", 1) or 1),
        timeout_s=int(raw.get("timeout_s", 1) or 1),
        deterministic_clock=bool(raw.get("deterministic_clock", True)),
        deterministic_random=bool(raw.get("deterministic_random", True)),
    )


__all__ = ["SandboxManifest", "manifest_from_mapping", "validate_manifest"]
