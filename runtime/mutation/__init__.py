# SPDX-License-Identifier: Apache-2.0
"""
runtime.mutation — Code Intelligence & Mutation Substrate
=========================================================
Provides the static-analysis and code-intelligence primitives used
by the ProposalEngine to enrich candidate mutations with structural,
historical, and hotspot context.

Sub-packages
------------
code_intel  — frozen code-intelligence snapshots (INTEL-ISO-0)
"""

from runtime.mutation.code_intel import (  # noqa: F401
    FunctionCallGraph,
    HotspotMap,
    MutationHistory,
    CodeIntelModel,
)

__all__ = [
    "FunctionCallGraph",
    "HotspotMap",
    "MutationHistory",
    "CodeIntelModel",
]
