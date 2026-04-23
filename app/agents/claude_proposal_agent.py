# SPDX-License-Identifier: Apache-2.0
"""Compatibility shim; import from adaad.agents.claude_proposal_agent instead."""

from app._deprecated_shim import warn_legacy_module

warn_legacy_module("app.agents.claude_proposal_agent", "adaad.agents.claude_proposal_agent")

from adaad.agents.claude_proposal_agent import *  # noqa: F401,F403
