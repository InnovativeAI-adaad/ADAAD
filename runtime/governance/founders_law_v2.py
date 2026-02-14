# SPDX-License-Identifier: Apache-2.0
"""Founders Law v2 module/manifest validation and federation negotiation."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
from typing import Iterable, Literal


SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$")

SCOPE_VALUES = {"local", "federated", "both"}
KIND_VALUES = {"core", "extension", "federation"}
SEVERITY_VALUES = {"hard", "soft", "advisory"}
COMPAT_FULL = "FULL_COMPATIBLE"
COMPAT_DOWNLEVEL = "DOWNLEVEL_COMPATIBLE"
COMPAT_INCOMPATIBLE = "INCOMPATIBLE"


@dataclass(frozen=True)
class LawRef:
    id: str
    version_range: str


@dataclass(frozen=True)
class LawRuleV2:
    rule_id: str
    name: str
    description: str
    severity: Literal["hard", "soft", "advisory"]
    applies_to: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LawModule:
    id: str
    version: str
    kind: Literal["core", "extension", "federation"]
    scope: Literal["local", "federated", "both"]
    applies_to: list[str] = field(default_factory=list)
    trust_modes: list[str] = field(default_factory=list)
    lifecycle_states: list[str] = field(default_factory=list)
    requires: list[LawRef] = field(default_factory=list)
    conflicts: list[LawRef] = field(default_factory=list)
    supersedes: list[LawRef] = field(default_factory=list)
    rules: list[LawRuleV2] = field(default_factory=list)


@dataclass(frozen=True)
class ManifestSignature:
    algo: str
    key_id: str
    value: str


@dataclass(frozen=True)
class LawManifest:
    schema_version: str
    node_id: str
    law_version: str
    trust_mode: str
    epoch_id: str
    modules: list[LawModule]
    signature: ManifestSignature


@dataclass(frozen=True)
class CompatibilityResult:
    compat_class: str
    compat_digest: str
    reasons: list[str]


def _parse_semver(value: str) -> tuple[int, int, int]:
    if not SEMVER_RE.match(value):
        raise ValueError(f"invalid semver: {value}")
    core = value.split("-", 1)[0].split("+", 1)[0]
    major, minor, patch = core.split(".")
    return int(major), int(minor), int(patch)


def _eval_clause(version: str, clause: str) -> bool:
    version_tuple = _parse_semver(version)
    clause = clause.strip()
    for op in (">=", "<=", ">", "<", "==", "="):
        if clause.startswith(op):
            rhs = clause[len(op) :].strip()
            rhs_tuple = _parse_semver(rhs)
            if op == ">=":
                return version_tuple >= rhs_tuple
            if op == "<=":
                return version_tuple <= rhs_tuple
            if op == ">":
                return version_tuple > rhs_tuple
            if op == "<":
                return version_tuple < rhs_tuple
            return version_tuple == rhs_tuple
    return version_tuple == _parse_semver(clause)


def semver_satisfies(version: str, version_range: str) -> bool:
    """Evaluate comma-delimited AND semver clauses (e.g. >=2.0.0,<3.0.0)."""
    clauses = [c.strip() for c in version_range.split(",") if c.strip()]
    if not clauses:
        return True
    return all(_eval_clause(version, clause) for clause in clauses)


def validate_manifest(manifest: LawManifest) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    module_map = {m.id: m for m in manifest.modules}

    for module in manifest.modules:
        if module.id in seen_ids:
            errors.append(f"duplicate module id: {module.id}")
        seen_ids.add(module.id)

        try:
            _parse_semver(module.version)
        except ValueError as exc:
            errors.append(str(exc))

        if module.kind not in KIND_VALUES:
            errors.append(f"invalid module kind for {module.id}: {module.kind}")
        if module.scope not in SCOPE_VALUES:
            errors.append(f"invalid module scope for {module.id}: {module.scope}")

        if manifest.trust_mode not in module.trust_modes:
            errors.append(f"module {module.id} does not support trust mode {manifest.trust_mode}")

        for dep in module.requires:
            target = module_map.get(dep.id)
            if target is None:
                errors.append(f"module {module.id} requires missing dependency {dep.id}")
                continue
            try:
                if not semver_satisfies(target.version, dep.version_range):
                    errors.append(
                        f"module {module.id} requires {dep.id}{dep.version_range}, found {target.version}"
                    )
            except ValueError as exc:
                errors.append(str(exc))

        for conflict in module.conflicts:
            target = module_map.get(conflict.id)
            if target is None:
                continue
            try:
                if semver_satisfies(target.version, conflict.version_range):
                    errors.append(
                        f"module {module.id} conflicts with active module {target.id}{conflict.version_range}"
                    )
            except ValueError as exc:
                errors.append(str(exc))

        for rule in module.rules:
            if rule.severity not in SEVERITY_VALUES:
                errors.append(f"invalid severity for {rule.rule_id}: {rule.severity}")
            unsupported = [scope for scope in rule.applies_to if scope not in module.applies_to]
            if unsupported:
                errors.append(
                    f"rule {rule.rule_id} applies_to {unsupported} not in module {module.id} applies_to"
                )

    return errors


def _active_conflict(a: LawModule, b: LawModule) -> bool:
    return any(ref.id == b.id and semver_satisfies(b.version, ref.version_range) for ref in a.conflicts)


def _missing_required(local: LawModule, peer_modules: dict[str, LawModule]) -> bool:
    for dep in local.requires:
        peer = peer_modules.get(dep.id)
        if peer is None:
            return True
        if not semver_satisfies(peer.version, dep.version_range):
            return True
    return False


def _is_downlevel_compatible(newer: LawManifest, older: LawManifest) -> bool:
    older_map = {m.id: m for m in older.modules}
    newer_map = {m.id: m for m in newer.modules}

    for old in older.modules:
        new = newer_map.get(old.id)
        if new is None:
            continue
        if _active_conflict(new, old) or _active_conflict(old, new):
            return False

    for mod in newer.modules:
        if mod.id in older_map:
            continue
        for dep in mod.requires:
            if dep.id in older_map and not semver_satisfies(older_map[dep.id].version, dep.version_range):
                return False
    return True


def _canonical_compat_view(a: LawManifest, b: LawManifest, compat_class: str) -> dict:
    a_modules = {m.id: m.version for m in a.modules}
    b_modules = {m.id: m.version for m in b.modules}
    intersection = sorted(set(a_modules).intersection(b_modules))
    return {
        "law_version_a": a.law_version,
        "law_version_b": b.law_version,
        "intersection": [
            {"id": module_id, "version_a": a_modules[module_id], "version_b": b_modules[module_id]}
            for module_id in intersection
        ],
        "class": compat_class,
    }


def _compat_digest(a: LawManifest, b: LawManifest, compat_class: str) -> str:
    payload = _canonical_compat_view(a, b, compat_class)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def evaluate_compatibility(a: LawManifest, b: LawManifest) -> CompatibilityResult:
    reasons: list[str] = []
    a_map = {m.id: m for m in a.modules}
    b_map = {m.id: m for m in b.modules}

    if a.law_version != b.law_version:
        compat_class = COMPAT_INCOMPATIBLE
        reasons.append("law_version mismatch without bridge")
        return CompatibilityResult(compat_class, _compat_digest(a, b, compat_class), reasons)

    for module_id in sorted(set(a_map).intersection(b_map)):
        left = a_map[module_id]
        right = b_map[module_id]
        if _active_conflict(left, right) or _active_conflict(right, left):
            compat_class = COMPAT_INCOMPATIBLE
            reasons.append(f"conflict active on shared module {module_id}")
            return CompatibilityResult(compat_class, _compat_digest(a, b, compat_class), reasons)

    for mod in a.modules:
        if _missing_required(mod, b_map):
            compat_class = COMPAT_INCOMPATIBLE
            reasons.append(f"requires unsatisfied from {mod.id} into peer")
            return CompatibilityResult(compat_class, _compat_digest(a, b, compat_class), reasons)

    for mod in b.modules:
        if _missing_required(mod, a_map):
            compat_class = COMPAT_INCOMPATIBLE
            reasons.append(f"requires unsatisfied from peer {mod.id} into local")
            return CompatibilityResult(compat_class, _compat_digest(a, b, compat_class), reasons)

    if len(a.modules) == len(b.modules) and all(m.id in b_map for m in a.modules):
        compat_class = COMPAT_FULL
    else:
        newer, older = (a, b) if len(a.modules) >= len(b.modules) else (b, a)
        compat_class = COMPAT_DOWNLEVEL if _is_downlevel_compatible(newer, older) else COMPAT_INCOMPATIBLE
        if compat_class == COMPAT_INCOMPATIBLE:
            reasons.append("downlevel constraints unsatisfied")

    return CompatibilityResult(compat_class, _compat_digest(a, b, compat_class), reasons)


NEGOTIATION_INIT = "INIT"
NEGOTIATION_MANIFEST_EXCHANGED = "MANIFEST_EXCHANGED"
NEGOTIATION_EVALUATED = "EVALUATED"
NEGOTIATION_AGREED = "AGREED"
NEGOTIATION_BOUND = "BOUND"
NEGOTIATION_REJECTED = "REJECTED"


@dataclass(frozen=True)
class NegotiationOutcome:
    state: str
    compat_class: str
    compat_digest: str


def negotiate_manifests(local: LawManifest, peer: LawManifest, peer_result: CompatibilityResult | None = None) -> NegotiationOutcome:
    """Deterministic handshake evaluation using compatibility class + digest matching."""
    local_result = evaluate_compatibility(local, peer)
    if local_result.compat_class == COMPAT_INCOMPATIBLE:
        return NegotiationOutcome(NEGOTIATION_REJECTED, local_result.compat_class, local_result.compat_digest)

    if peer_result is None:
        return NegotiationOutcome(NEGOTIATION_EVALUATED, local_result.compat_class, local_result.compat_digest)

    if peer_result.compat_class == COMPAT_INCOMPATIBLE:
        return NegotiationOutcome(NEGOTIATION_REJECTED, peer_result.compat_class, peer_result.compat_digest)

    if (
        peer_result.compat_class == local_result.compat_class
        and peer_result.compat_digest == local_result.compat_digest
        and local_result.compat_class in {COMPAT_FULL, COMPAT_DOWNLEVEL}
    ):
        return NegotiationOutcome(NEGOTIATION_BOUND, local_result.compat_class, local_result.compat_digest)

    return NegotiationOutcome(NEGOTIATION_REJECTED, local_result.compat_class, local_result.compat_digest)


def manifest_digest(manifest: LawManifest) -> str:
    encoded = json.dumps(manifest, default=lambda o: o.__dict__, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def module_ids(modules: Iterable[LawModule]) -> set[str]:
    return {m.id for m in modules}


__all__ = [
    "COMPAT_DOWNLEVEL",
    "COMPAT_FULL",
    "COMPAT_INCOMPATIBLE",
    "CompatibilityResult",
    "KIND_VALUES",
    "LawManifest",
    "LawModule",
    "LawRef",
    "LawRuleV2",
    "ManifestSignature",
    "NEGOTIATION_AGREED",
    "NEGOTIATION_BOUND",
    "NEGOTIATION_EVALUATED",
    "NEGOTIATION_INIT",
    "NEGOTIATION_MANIFEST_EXCHANGED",
    "NEGOTIATION_REJECTED",
    "NegotiationOutcome",
    "evaluate_compatibility",
    "manifest_digest",
    "module_ids",
    "negotiate_manifests",
    "semver_satisfies",
    "validate_manifest",
]
