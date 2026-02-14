# SPDX-License-Identifier: Apache-2.0
"""Network egress allowlist checks."""

from __future__ import annotations

from typing import Iterable, Tuple


def enforce_network_egress_allowlist(observed_hosts: Iterable[str], allowlist: Tuple[str, ...]) -> tuple[bool, tuple[str, ...]]:
    allowed = set(str(item) for item in allowlist)
    violations = tuple(sorted({str(host) for host in observed_hosts if str(host) not in allowed}))
    return (len(violations) == 0, violations)


__all__ = ["enforce_network_egress_allowlist"]
