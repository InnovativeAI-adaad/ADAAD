# SPDX-License-Identifier: Apache-2.0
"""
app/api/cpve.py
Phase 223 · INNOV-128 · CPVE — Constitutional Provenance Verification Engine
FastAPI router wired from dorkllm.cpve_router
Author: DEVADAAD · InnovativeAI LLC · Governor: DUSTIN L REID
"""

from dorkllm.cpve_router import router  # noqa: F401 — re-export

__all__ = ["router"]
