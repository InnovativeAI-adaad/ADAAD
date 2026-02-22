# SPDX-License-Identifier: Apache-2.0

import pytest

from runtime.sandbox.manifest import SandboxManifest, validate_manifest
from runtime.sandbox.policy import SandboxPolicy, validate_policy


def test_manifest_validation_rejects_zero_seed():
    manifest = SandboxManifest(
        mutation_id="m",
        epoch_id="e",
        replay_seed="0000000000000000",
        command=("pytest",),
        env=(),
        mounts=(),
        allowed_write_paths=("reports",),
        allowed_network_hosts=(),
        cpu_seconds=1,
        memory_mb=1,
        disk_mb=1,
        timeout_s=1,
        deterministic_clock=True,
        deterministic_random=True,
    )
    with pytest.raises(ValueError, match="invalid_replay_seed_zero"):
        validate_manifest(manifest)


def test_policy_validation_rejects_empty_profile():
    policy = SandboxPolicy(
        profile_id="",
        syscall_allowlist=("read",),
        write_path_allowlist=("reports",),
        network_egress_allowlist=(),
        dns_resolution_allowed=False,
        capability_drop=(),
        cpu_seconds=1,
        memory_mb=1,
        disk_mb=1,
        timeout_s=1,
    )
    with pytest.raises(ValueError, match="invalid_policy_profile_id"):
        validate_policy(policy)
