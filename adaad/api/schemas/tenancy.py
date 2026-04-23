# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class TenantContext(BaseModel):
    """Resolved tenant scope for one API request lifecycle."""

    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: StrictStr = Field(min_length=1, max_length=128)
    workspace_id: StrictStr = Field(min_length=1, max_length=128)
