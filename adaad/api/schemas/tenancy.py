# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pydantic import Field, StrictStr
from adaad.api.schemas._compat import BaseModelCompatStrict as _Base


class TenantContext(_Base):
    """Resolved tenant scope for one API request lifecycle."""

    tenant_id: StrictStr = Field(min_length=1, max_length=128)
    workspace_id: StrictStr = Field(min_length=1, max_length=128)
