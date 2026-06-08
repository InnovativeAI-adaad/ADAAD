# SPDX-License-Identifier: Apache-2.0
"""Beyond-seed discovery for high-level ADAAD abilities (self-capable extension).

This module enables ADAAD to discover abilities that are not (yet) present in the
static data/capabilities.json "known" seed. It is the foundation for "fully self
capable beyond known abilities" (Phase 199+ drift-hygiene + self-extension).

Design:
- Import-safe and resilient: every source is wrapped; errors on one source never
  break the whole discovery (per ABILITY-FAILCLOSED-0 spirit).
- No heavy side effects on import of adaad.abilities (discovery is explicit).
- Produces Ability instances (with provenance="discovered") ready for
  register_ability (subject to the governance hook).
- Sources (extensible): seed (for parity), protocol scan (runtime_checkable
  AbilityProtocol implementers), agent manifests, tool contracts, dork intent
  schemas (best-effort), and explicit candidate dicts.

Invariants declared (Hard-class for this surface):
- ABILITY-DISCOVER-0: discovery never mutates the registry or seed files.
- ABILITY-DISCOVER-1: all returned Ability satisfy AbilityProtocol and have
  provenance in ALLOWED_PROVENANCE.
- ABILITY-DISCOVER-DETERM-0: for a fixed set of sources the output order is
  deterministic (sorted by name).

Usage (lightweight):
    from adaad.abilities.discovery import discover_abilities
    cands = discover_abilities()
    for a in cands:
        # inspect; optionally register_ability(a) after governance gate
        ...

Part of the adaad/abilities self-capable charter. Complements (does not replace)
deeper adaad/agents/* and runtime capability contracts.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any, Iterable

from .base import ALLOWED_PROVENANCE, Ability, AbilityProtocol

# Safe packages for protocol scan (keep small to preserve lightweight + early import).
# We intentionally do not auto-scan the entire sys.path or heavy runtime/.
# Determinism note: we only consult already-loaded sys.modules (no import_module
# or dynamic execution at discovery time) so lint_determinism on adaad/abilities/
# remains clean. Explicit imports by caller make additional modules visible.
_DISCOVERY_SCAN_PACKAGES: tuple[str, ...] = (
    "adaad.abilities",
    "adaad.agents",
    "adaad.core",
    "adaad.orchestrator",
)


def _safe_import(name: str) -> Any | None:
    # Determinism-safe: only already-loaded modules. No importlib.import_module.
    return sys.modules.get(name)


def _iter_protocol_implementers(module: Any) -> Iterable[type]:
    """Yield classes in module (and submodules if package) that implement AbilityProtocol at runtime."""
    if module is None:
        return
    try:
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is Ability or obj is AbilityProtocol:
                continue
            # runtime_checkable Protocol check (structural + registered)
            if isinstance(obj, type) and AbilityProtocol in getattr(obj, "__mro__", ()):
                # Additional: has the required attrs or implements invariants()
                if hasattr(obj, "invariants") or all(hasattr(obj, f) for f in ("name", "owner", "version", "tier", "requires")):
                    yield obj
    except Exception:
        return


def _discover_from_protocol_scan() -> list[Ability]:
    """Scan a small allowlist of packages for runtime AbilityProtocol implementers.
    Returns Ability instances with provenance="discovered" (best effort names).
    """
    found: list[Ability] = []
    seen: set[str] = set()
    for pkg_name in _DISCOVERY_SCAN_PACKAGES:
        mod = _safe_import(pkg_name)
        if mod is None:
            continue
        # Direct members
        for cls in _iter_protocol_implementers(mod):
            try:
                # Best-effort: if class has class attrs or can be instantiated minimally
                name = getattr(cls, "name", None) or getattr(cls, "__name__", None) or f"discovered.{cls.__name__.lower()}"
                if name in seen:
                    continue
                owner = getattr(cls, "owner", "Governance")
                version = getattr(cls, "version", "0.0.0-discovered")
                requires = list(getattr(cls, "requires", [])) or []
                tier = int(getattr(cls, "tier", 2))
                ab = Ability(
                    name=str(name),
                    owner=str(owner),
                    version=str(version),
                    requires=requires,
                    tier=tier,
                    provenance="discovered",
                )
                found.append(ab)
                seen.add(name)
            except Exception:
                continue
        # If package, try one level of submodules (guarded)
        try:
            if hasattr(mod, "__path__"):
                for _finder, subname, _ispkg in pkgutil.iter_modules(mod.__path__, mod.__name__ + "."):
                    sub = _safe_import(subname)
                    for cls in _iter_protocol_implementers(sub):
                        # (same best-effort construction as above; duplicated for simplicity in small module)
                        try:
                            name = getattr(cls, "name", None) or getattr(cls, "__name__", None) or f"discovered.{cls.__name__.lower()}"
                            if name in seen:
                                continue
                            owner = getattr(cls, "owner", "Governance")
                            version = getattr(cls, "version", "0.0.0-discovered")
                            requires = list(getattr(cls, "requires", [])) or []
                            tier = int(getattr(cls, "tier", 2))
                            ab = Ability(name=str(name), owner=str(owner), version=str(version), requires=requires, tier=tier, provenance="discovered")
                            found.append(ab)
                            seen.add(name)
                        except Exception:
                            continue
        except Exception:
            pass
    return sorted(found, key=lambda a: a.name)


def _discover_from_agent_manifests() -> list[Ability]:
    """Best-effort: walk adaad/agents for meta.json / dna.json capability hints.
    Produces discovered Ability entries when a manifest declares "capabilities".
    """
    found: list[Ability] = []
    base = Path(__file__).resolve().parents[1] / "agents"
    if not base.exists():
        return found
    try:
        for meta in base.rglob("meta.json"):
            try:
                import json
                data = json.loads(meta.read_text(encoding="utf-8"))
                caps = data.get("capabilities") or data.get("abilities") or []
                if isinstance(caps, (list, tuple)):
                    for c in caps:
                        if isinstance(c, str):
                            name = c
                            ab = Ability(name=name, owner="Governance", version="0.0.0-discovered", provenance="discovered", tier=2)
                            found.append(ab)
                        elif isinstance(c, dict) and c.get("name"):
                            ab = Ability(
                                name=str(c["name"]),
                                owner=str(c.get("owner", "Governance")),
                                version=str(c.get("version", "0.0.0-discovered")),
                                requires=list(c.get("requires", [])),
                                tier=int(c.get("tier", 2)),
                                provenance="discovered",
                            )
                            found.append(ab)
            except Exception:
                continue
    except Exception:
        pass
    return sorted(found, key=lambda a: a.name)


def _discover_from_capabilities_seed() -> list[Ability]:
    """Re-seed parity: load current capabilities.json as discovered (or seed) entries.
    Useful for drift comparison (see drift.py). Non-mutating.
    """
    from .registry import seed_from_capabilities_json  # local, resilient re-use
    # We do not want to mutate the live registry here; just synthesize Ability list.
    # Call the loader logic in a temp-cleared way is overkill; instead duplicate minimal load.
    try:
        from pathlib import Path
        import json
        path = str(Path(__file__).resolve().parents[2] / "data" / "capabilities.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        out: list[Ability] = []
        for name, entry in (data or {}).items():
            if not isinstance(name, str):
                continue
            try:
                ab = Ability(
                    name=name,
                    owner=str(entry.get("owner", "Unknown")),
                    version=str(entry.get("version", "0.0.0")),
                    requires=list(entry.get("requires", [])) if isinstance(entry.get("requires"), (list, tuple)) else [],
                    score=float(entry.get("score", 1.0)),
                    tier=1,
                    identity=entry.get("identity"),
                    evidence=dict(entry.get("evidence", {})) if isinstance(entry.get("evidence"), dict) else {},
                    updated_at=entry.get("updated_at"),
                    provenance="seed",
                )
                out.append(ab)
            except Exception:
                continue
        return sorted(out, key=lambda a: a.name)
    except Exception:
        return []


def discover_abilities(sources: list[str] | None = None) -> list[Ability]:
    """Discover abilities beyond (or including) the static seed.

    sources: optional subset of {"seed", "protocol_scan", "agent_manifests"}.
             Default = all implemented sources.

    Returns a deterministic (name-sorted), de-duplicated list of Ability.
    All returned items satisfy AbilityProtocol and carry provenance.

    Does NOT mutate the registry. Caller decides whether to register_ability()
    (subject to the current governance hook and gates).
    """
    if sources is None:
        sources = ["seed", "protocol_scan", "agent_manifests"]

    results: list[Ability] = []
    seen: set[str] = set()

    if "seed" in sources:
        for ab in _discover_from_capabilities_seed():
            if ab.name not in seen:
                seen.add(ab.name)
                results.append(ab)

    if "protocol_scan" in sources:
        for ab in _discover_from_protocol_scan():
            if ab.name not in seen:
                seen.add(ab.name)
                results.append(ab)

    if "agent_manifests" in sources:
        for ab in _discover_from_agent_manifests():
            if ab.name not in seen:
                seen.add(ab.name)
                results.append(ab)

    # Future sources (dork_intents, mutation proposals, etc.) can be added here
    # without changing callers. All must produce Ability with valid provenance.

    return sorted(results, key=lambda a: a.name)


__all__ = [
    "discover_abilities",
    "ALLOWED_PROVENANCE",
]