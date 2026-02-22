# SPDX-License-Identifier: Apache-2.0
"""Network egress allowlist checks."""

from __future__ import annotations

import ipaddress
from typing import Iterable, Tuple


def _requires_dns_resolution(host: str) -> bool:
    candidate = host.strip().lower()
    if not candidate or candidate in {"localhost", "dns"}:
        return False
    try:
        ipaddress.ip_address(candidate)
        return False
    except ValueError:
        return True


def enforce_network_egress_allowlist(
    observed_hosts: Iterable[str], allowlist: Tuple[str, ...], dns_resolution_allowed: bool = False
) -> tuple[bool, tuple[str, ...]]:
    allowed = set(str(item) for item in allowlist)
    violations: set[str] = set()
    for raw_host in observed_hosts:
        host = str(raw_host)
        if _requires_dns_resolution(host) and not dns_resolution_allowed:
            violations.add("dns")
        if host not in allowed:
            violations.add(host)
    violation_tuple = tuple(sorted(violations))
    return (len(violation_tuple) == 0, violation_tuple)


__all__ = ["enforce_network_egress_allowlist"]
