# SPDX-License-Identifier: Apache-2.0
"""
Pydantic v1 / v2 compatibility shim for ADAAD schema layer.

Termux (armv8l / aarch64) ships pydantic v1 (pure Python, no Rust).
Desktop / CI runs pydantic v2.

Usage
-----
    from adaad.api.schemas._compat import BaseModelCompat, field_required

    class MyModel(BaseModelCompat):
        name: str

On pydantic v2  → BaseModelCompat is BaseModel with ConfigDict(extra="forbid")
On pydantic v1  → BaseModelCompat is BaseModel with inner class Config
"""
from __future__ import annotations

from pydantic import BaseModel
from pydantic.version import VERSION as _PYDANTIC_VERSION

PYDANTIC_V2: bool = int(_PYDANTIC_VERSION.split(".")[0]) >= 2


if PYDANTIC_V2:
    from pydantic import ConfigDict  # noqa: F401  (re-export for callers)

    class BaseModelCompat(BaseModel):
        model_config = ConfigDict(extra="forbid")

    class BaseModelCompatStrict(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)

else:
    # pydantic v1 — ConfigDict does not exist; use inner Config class
    ConfigDict = None  # type: ignore[assignment,misc]

    class BaseModelCompat(BaseModel):  # type: ignore[no-redef]
        class Config:
            extra = "forbid"

    class BaseModelCompatStrict(BaseModel):  # type: ignore[no-redef]
        class Config:
            extra = "forbid"
