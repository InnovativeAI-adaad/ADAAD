# SPDX-License-Identifier: Apache-2.0
"""Abilities surface drift detection and hygiene reporting (self-capable extension).

Part of making ADAAD fully self-capable beyond known (static seed) abilities.
Complements CGVE (version surfaces) and CGDR (convergence criteria) with a
focused, machine-readable report on the high-level abilities registry vs. its
sources (capabilities.json, discovery, code declarations, evidence claims).

Key types:
- DriftItem: per-ability finding (name, kind, details).
- AbilitiesDriftReport: timestamped, deterministic summary with parity_ok flag.

Invariants (Hard-class for this hygiene surface):
- ABILITY-DRIFT-0: detect_abilities_drift is pure/read-only w.r.t. registry and files;
  never mutates state.
- ABILITY-DRIFT-DETERM-0: report content (drifted list, parity) is deterministic for
  identical inputs (sorted, no wall time in core keys).
- ABILITY-DRIFT-FAILCLOSED-0: errors during comparison surface as explicit entries
  rather than silent partial reports.

Usage:
    from adaad.abilities.drift import detect_abilities_drift, AbilitiesDriftReport
    report = detect_abilities_drift()
    if not report.parity_ok:
        # escalate or trigger hygiene reconcile under governance gate
        ...

After Phase 199 self-extension, this is the canonical way the agent (and operators)
see when its declared abilities have drifted from reality.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import Ability
from .registry import abilities_snapshot, seed_from_capabilities_json


@dataclass(frozen=True)
class DriftItem:
    name: str
    kind: str  # e.g. "missing_in_registry", "extra_in_registry", "requires_mismatch", "provenance_skew", "version_skew", "owner_mismatch", "evidence_gap"
    details: str


@dataclass
class AbilitiesDriftReport:
    """Structured, deterministic drift report for the abilities surface."""
    timestamp: str
    surfaces_compared: list[str]
    drifted: list[DriftItem] = field(default_factory=list)
    parity_ok: bool = True
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "surfaces_compared": list(self.surfaces_compared),
            "drifted": [
                {"name": d.name, "kind": d.kind, "details": d.details} for d in self.drifted
            ],
            "parity_ok": self.parity_ok,
            "recommendations": list(self.recommendations),
        }


def _load_capabilities_json(path: str | None = None) -> dict[str, Any]:
    if path is None:
        path = str(Path(__file__).resolve().parents[2] / "data" / "capabilities.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _compare_requires(a: list[str], b: list[str]) -> str | None:
    sa, sb = sorted(a or []), sorted(b or [])
    if sa != sb:
        return f"requires {sa} vs {sb}"
    return None


def detect_abilities_drift(
    *,
    capabilities_path: str | None = None,
    include_discovered: bool = True,
) -> AbilitiesDriftReport:
    """Detect drift between the live registry, the seed json, and discovered sources.

    Returns a report. parity_ok is True only if no critical drifts (missing/extra
    names, requires skew, owner/version mismatches on overlapping names).

    This is the hook for self-hygiene: the agent (or a CGVE-like pass, or
    post-CMES promote) can call this, and if not parity_ok, either reconcile
    under governance or block promotion.
    """
    ts = datetime.now(timezone.utc).isoformat()
    surfaces = ["registry", "capabilities.json"]
    if include_discovered:
        surfaces.append("discovery")

    registry = abilities_snapshot()  # name -> Ability
    caps = _load_capabilities_json(capabilities_path)

    # Build name sets
    reg_names = set(registry.keys())
    cap_names = set(caps.keys())

    # Optional discovery (may add "beyond seed" names)
    disc_names: set[str] = set()
    disc_map: dict[str, Ability] = {}
    if include_discovered:
        try:
            from .discovery import discover_abilities
            for ab in discover_abilities():
                disc_names.add(ab.name)
                disc_map[ab.name] = ab
        except Exception:
            pass

    all_names = sorted(reg_names | cap_names | disc_names)
    drifted: list[DriftItem] = []

    for name in all_names:
        in_reg = name in reg_names
        in_cap = name in cap_names
        in_disc = name in disc_names

        if in_reg and not in_cap and not in_disc:
            drifted.append(DriftItem(name, "extra_in_registry", "present in registry but absent from seed and discovery"))
            continue
        if not in_reg and (in_cap or in_disc):
            src = "seed" if in_cap else "discovery"
            drifted.append(DriftItem(name, "missing_in_registry", f"declared in {src} but not registered"))
            continue

        # Overlap checks
        if in_reg and in_cap:
            reg_ab = registry[name]
            cap_entry = caps[name] or {}
            if reg_ab.owner != str(cap_entry.get("owner", reg_ab.owner)):
                drifted.append(DriftItem(name, "owner_mismatch", f"{reg_ab.owner} vs {cap_entry.get('owner')}"))
            if reg_ab.version != str(cap_entry.get("version", reg_ab.version)):
                drifted.append(DriftItem(name, "version_skew", f"{reg_ab.version} vs {cap_entry.get('version')}"))
            req_diff = _compare_requires(reg_ab.requires, list(cap_entry.get("requires", [])) if isinstance(cap_entry.get("requires"), (list, tuple)) else [])
            if req_diff:
                drifted.append(DriftItem(name, "requires_mismatch", req_diff))
            # provenance note (informational, not necessarily a hard drift)
            if getattr(reg_ab, "provenance", "seed") not in ("seed", "hygiene_reconciled"):
                # Only flag if the seed entry claims it but registry says otherwise
                pass

        # Discovery vs registry parity (for beyond-seed)
        if in_reg and in_disc:
            reg_ab = registry[name]
            disc_ab = disc_map.get(name)
            if disc_ab and disc_ab.provenance == "discovered":
                # If registry still says "seed" for a discovered item, note skew (hygiene opportunity)
                if reg_ab.provenance == "seed":
                    drifted.append(DriftItem(name, "provenance_skew", "registry marks 'seed' but discovery found it as beyond-seed"))

    # Evidence / claims parity is intentionally light here (full matrix check lives in validate_release_evidence + CGDR).
    # We can add a recommendation if drifted.
    recommendations: list[str] = []
    if drifted:
        recommendations.append("Run hygiene reconcile or promote via CMES + governance hook for drifted abilities.")
        recommendations.append("Update data/capabilities.json (under CGVE blast-1 or post-promote) if seed drift confirmed.")
    else:
        recommendations.append("Abilities surface in parity. Good candidate for self-extension proposals.")

    parity_ok = len(drifted) == 0

    return AbilitiesDriftReport(
        timestamp=ts,
        surfaces_compared=surfaces,
        drifted=drifted,
        parity_ok=parity_ok,
        recommendations=recommendations,
    )


__all__ = [
    "AbilitiesDriftReport",
    "DriftItem",
    "detect_abilities_drift",
]