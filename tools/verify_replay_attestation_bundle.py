# SPDX-License-Identifier: Apache-2.0
"""Deterministic offline verifier for replay attestation bundles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from runtime.evolution.replay_attestation import load_replay_proof, verify_replay_proof_bundle
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from runtime.evolution.replay_attestation import load_replay_proof, verify_replay_proof_bundle


def _load_json_file(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _build_revocation_source(revocation_data: Mapping[str, Any] | None):
    entries = list((revocation_data or {}).get("revoked", []))

    def _resolver(*, key_id: str, trust_metadata: Mapping[str, Any], revocation_reference: Any) -> bool:
        reference = ""
        source = ""
        if isinstance(revocation_reference, dict):
            reference = str(revocation_reference.get("reference") or "")
            source = str(revocation_reference.get("source") or "")
        _ = trust_metadata
        for item in entries:
            if not isinstance(item, dict):
                continue
            if str(item.get("key_id") or "") != key_id:
                continue
            if source and str(item.get("source") or "") != source:
                continue
            if reference and str(item.get("reference") or "") != reference:
                continue
            return True
        return False

    return _resolver


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an exported replay attestation bundle deterministically.")
    parser.add_argument("bundle", type=Path, help="Path to replay_attestation.v1.json bundle")
    parser.add_argument("--keyring", type=Path, help="JSON map of key_id -> key material")
    parser.add_argument("--accepted-issuers", nargs="*", default=None, help="Accepted issuer ids")
    parser.add_argument("--key-validity-windows", type=Path, help="JSON map of key epoch id to validity windows")
    parser.add_argument("--revocations", type=Path, help='JSON document with "revoked" entries')
    parser.add_argument("--trust-policy-version", type=str, help="Expected trust policy version")
    args = parser.parse_args(list(argv) if argv is not None else None)

    bundle = load_replay_proof(args.bundle)
    keyring = _load_json_file(args.keyring) if args.keyring else None
    key_validity_windows = _load_json_file(args.key_validity_windows) if args.key_validity_windows else None
    revocations = _load_json_file(args.revocations) if args.revocations else None
    revocation_source = _build_revocation_source(revocations) if revocations is not None else None

    result = verify_replay_proof_bundle(
        bundle,
        keyring=keyring,
        accepted_issuers=args.accepted_issuers,
        key_validity_windows=key_validity_windows,
        revocation_source=revocation_source,
        trust_policy_version=args.trust_policy_version,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
