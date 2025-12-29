from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any, Dict

from security.canonical import canonical_json


def verify_cryovant_signature(key: str, mac_input: Dict[str, Any], signature: str) -> bool:
    canonical_payload = canonical_json(mac_input)
    expected = hmac.new(key.encode("utf-8"), canonical_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_iso8601(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts).astimezone(timezone.utc)


def within_window(timestamp_iso: str, max_skew_seconds: int = 60) -> bool:
    dt = parse_iso8601(timestamp_iso)
    now = datetime.now(timezone.utc)
    delta = abs((now - dt).total_seconds())
    return delta <= max_skew_seconds


__all__ = [
    "verify_cryovant_signature",
    "parse_iso8601",
    "within_window",
]
