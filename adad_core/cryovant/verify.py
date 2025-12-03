"""Verification helpers for Cryovant signatures."""
from __future__ import annotations

import hmac
import hashlib
import os
from pathlib import Path
from typing import Optional

from adad_core.cryovant.signer import file_digest, DEFAULT_SECRET_ENV


def verify_signature(path: Path, signature: str, secret: Optional[str] = None) -> bool:
    """Verify a signature produced by :func:`sign_path`.

    HMAC signatures are preferred when a secret is available; otherwise
    raw digest verification is used.
    """
    if signature.startswith("hmac256:"):
        key = (secret or os.getenv(DEFAULT_SECRET_ENV) or "").encode("utf-8")
        if not key:
            return False
        expected = signature.split(":", 1)[1]
        digest = file_digest(path)
        mac = hmac.new(key, digest.encode("utf-8"), hashlib.sha256)
        return hmac.compare_digest(mac.hexdigest(), expected)
    if signature.startswith("sha256:"):
        expected = signature.split(":", 1)[1]
        return file_digest(path) == expected
    return False


def verify_signature_file(path: Path, signature_path: Optional[Path] = None, secret: Optional[str] = None) -> bool:
    """Verify a stored signature file."""
    signature_path = signature_path or path.with_suffix(path.suffix + ".sig")
    if not signature_path.exists():
        return False
    signature = signature_path.read_text(encoding="utf-8").strip()
    return verify_signature(path, signature, secret=secret)
