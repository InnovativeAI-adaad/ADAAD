# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


SIGN_SCRIPT = Path("scripts/sign_policy_artifact.sh")
VERIFY_SCRIPT = Path("scripts/verify_policy_artifact.sh")


def test_sign_and_verify_policy_scripts_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "policy.json"
    signed = tmp_path / "policy.signed.json"
    source.write_text(Path("governance/governance_policy_v1.json").read_text(encoding="utf-8"), encoding="utf-8")

    env = dict(os.environ)
    env["ADAAD_POLICY_ARTIFACT_SIGNING_KEY"] = "script-test-signing-key"
    env["ADAAD_POLICY_SIGNER_KEY_ID"] = "script-signer"

    sign = subprocess.run(
        [str(SIGN_SCRIPT), str(source), str(signed)],
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    assert str(signed) in sign.stdout

    artifact = json.loads(signed.read_text(encoding="utf-8"))
    assert artifact["signer"]["key_id"] == "script-signer"
    assert artifact["signer"]["algorithm"] == "hmac-sha256"
    assert artifact["signature"].startswith("sha256:")

    verify = subprocess.run(
        [str(VERIFY_SCRIPT), str(signed)],
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    assert verify.stdout.strip().startswith("sha256:")
