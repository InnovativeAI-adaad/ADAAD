# SPDX-License-Identifier: Apache-2.0

from governance.foundation.canonical import canonical_json
from governance.foundation.hashing import sha256_digest
from runtime.governance.foundation.clock import utc_now_iso


def test_canonical_json_is_sorted_and_compact() -> None:
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'


def test_sha256_digest_uses_canonical_payload() -> None:
    left = sha256_digest({"a": 1, "b": 2})
    right = sha256_digest({"b": 2, "a": 1})
    assert left == right


def test_utc_now_iso_has_z_suffix() -> None:
    assert utc_now_iso().endswith("Z")
