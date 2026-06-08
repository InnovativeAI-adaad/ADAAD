# SPDX-License-Identifier: Apache-2.0
"""Lightweight Ability description (protocol + concrete dataclass).

This is the formal base for high-level ADAAD abilities. It is kept
intentionally minimal so that adaad.abilities can be imported alone.

An Ability captures the identity, ownership (5-element model), dependency
declarations, and optional governance metadata for things like
cmce.consensus, dream.cycle, architect.scan, etc.

Future: Ability can evolve into a typing.Protocol once more surfaces
(execution, scoring, UI wiring) are added.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Protocol, runtime_checkable

# Allowed provenance values for self-capable abilities (beyond static seed).
# Enables discovery, synthesis via AMPS/CMES, promotion, and hygiene reconciliation
# while preserving the lightweight importable-alone contract.
ALLOWED_PROVENANCE: tuple[str, ...] = (
    "seed",
    "discovered",
    "synthesized",
    "promoted_via_cmes",
    "hygiene_reconciled",
)


@runtime_checkable
class AbilityProtocol(Protocol):
    """Strict protocol for high-level ADAAD Ability.

    Implementations (e.g. the dataclass below) MUST provide:
    - name: str
    - owner: str
    - version: str
    - tier: int
    - requires: list[str]
    - invariants() -> list[str]
    """
    name: str
    owner: str
    version: str
    tier: int
    requires: list[str]

    def invariants(self) -> list[str]: ...


@dataclass(frozen=True)
class Ability:
    """High-level ADAAD ability (implements AbilityProtocol for structural typing).

    This dataclass provides the concrete implementation of the lightweight
    Ability protocol. The package (adaad/abilities) is designed to be
    importable in complete isolation.

    Attributes
    ----------
    name:
        Dotted or kebab identifier, e.g. "cmce.consensus", "dream.cycle".
    owner:
        Element owner: "Earth" | "Water" | "Wood" | "Fire" | "Metal".
    version:
        Semantic version string.
    requires:
        Other ability names this one depends on (for ordering / visibility).
    score:
        Default fitness / availability score (0.0-1.0).
    tier:
        0=constitutional, 1=core, 2=extension (used by list_abilities).
    identity:
        Optional cryptographically stamped identity dict (tool_id, version,
        hash, timestamp) as produced by runtime.manifest.generator or
        adaad.core.cryovant.
    evidence:
        Optional governance evidence bag (populated by Phase 199+ artifacts).
    updated_at:
        ISO timestamp of last registration / update.
    provenance:
        Source of the ability declaration for self-capability (Phase 199+ self-extension).
        One of ALLOWED_PROVENANCE. "seed" for data/capabilities.json; "discovered",
        "synthesized", "promoted_via_cmes", or "hygiene_reconciled" for beyond-known.
    """

    # The dataclass provides extra fields for compatibility with data/capabilities.json
    # and previous high-level registrations, but the strict AbilityProtocol only
    # requires the listed attributes + invariants().

    name: str
    owner: str
    version: str
    requires: list[str] = field(default_factory=list)
    score: float = 1.0
    tier: int = 1
    identity: Mapping[str, Any] | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    updated_at: str | None = None
    provenance: str = "seed"

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError("Ability.name must be a non-empty string")
        if self.owner not in {"Earth", "Water", "Wood", "Fire", "Metal", "Governance"}:
            # Allow "Governance" etc. for future/self meta-abilities, but warn via convention
            pass
        if self.tier not in (0, 1, 2):
            raise ValueError("Ability.tier must be 0, 1, or 2")
        if self.provenance not in ALLOWED_PROVENANCE:
            raise ValueError(f"Ability.provenance must be one of {ALLOWED_PROVENANCE}, got {self.provenance!r}")

    def invariants(self) -> list[str]:
        """Return list of invariant strings this Ability claims to uphold.

        This is required by the strict AbilityProtocol.
        Extended for self-capable (Phase 199+): includes provenance (ABILITY-PROV-0).
        """
        invs = [
            f"ABILITY-NAME-0: {self.name}",
            f"ABILITY-OWNER-0: {self.owner}",
            f"ABILITY-VERSION-0: {self.version}",
            f"ABILITY-TIER-0: {self.tier}",
            f"ABILITY-REQUIRES-0: {self.requires}",
            f"ABILITY-PROV-0: {self.provenance}",
        ]
        return invs

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for JSON / capabilities.json.
        Includes provenance for self-capable beyond-known tracking.
        """
        d: dict[str, Any] = {
            "name": self.name,
            "owner": self.owner,
            "version": self.version,
            "requires": list(self.requires),
            "score": self.score,
            "tier": self.tier,
            "provenance": self.provenance,
        }
        if self.identity is not None:
            d["identity"] = dict(self.identity)
        if self.evidence:
            d["evidence"] = dict(self.evidence)
        if self.updated_at:
            d["updated_at"] = self.updated_at
        return d
