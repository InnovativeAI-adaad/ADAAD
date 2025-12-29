# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Lightweight Cryovant-style signer based on SHA-256 hashes.

To keep the dependency footprint minimal, signatures are implemented as
HMAC-SHA256 strings backed by a user-provided secret. If no secret is
available, the function falls back to a plain digest, still useful for
integrity checking.
"""
from __future__ import annotations

import hmac
import hashlib
import os
from pathlib import Path
from typing import Optional

DEFAULT_SECRET_ENV = "CRYOVANT_SECRET"


def file_digest(path: Path) -> str:
    """Return the hex SHA-256 digest of ``path``."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def sign_path(path: Path, secret: Optional[str] = None) -> str:
    """Return an integrity signature for ``path``.

    The secret is resolved in the following order:
    1. Explicit ``secret`` argument
    2. Environment variable ``CRYOVANT_SECRET``
    3. ``None`` → raw digest with ``sha256:`` prefix
    """
    digest = file_digest(path)
    key = (secret or os.getenv(DEFAULT_SECRET_ENV) or "").encode("utf-8")
    if not key:
        return f"sha256:{digest}"
    mac = hmac.new(key, digest.encode("utf-8"), hashlib.sha256)
    return f"hmac256:{mac.hexdigest()}"


def write_signature(path: Path, signature_path: Optional[Path] = None, secret: Optional[str] = None) -> Path:
    """Write a signature file next to ``path`` and return its location."""
    sig = sign_path(path, secret=secret)
    signature_path = signature_path or path.with_suffix(path.suffix + ".sig")
    signature_path.parent.mkdir(parents=True, exist_ok=True)
    signature_path.write_text(sig, encoding="utf-8")
    return signature_path