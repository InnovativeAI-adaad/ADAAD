# Founders Law v2: Module Manifest + Federation Negotiation

Founders Law v2 moves governance from a single policy surface to composable, independently versioned law modules. This document defines the runtime model used by `runtime/governance/founders_law_v2.py`.

## Law module model

Each module includes:

- `id`, `version`, `kind`, `scope`
- applicability (`applies_to`, `trust_modes`, `lifecycle_states`)
- dependency semantics (`requires`, `conflicts`, `supersedes`)
- a versioned rule inventory (`rule_id`, severity, and scope)

## Node law manifest

Each node publishes one manifest that is signed and bound to epoch context.

Required top-level fields:

- `schema_version`
- `node_id`
- `law_version`
- `trust_mode`
- `epoch_id`
- `modules[]`
- `signature`

## Manifest validation

Runtime checks enforce:

1. Unique module IDs.
2. Valid semver for module versions and semver-range constraints.
3. Satisfied `requires` dependencies.
4. No active `conflicts` pair.
5. Node trust mode must be allowed by every active module.
6. Rule severity values limited to `hard | soft | advisory`.
7. Rule-level `applies_to` must be a subset of module-level `applies_to`.

## Compatibility classes

Two manifests are compared with deterministic outcomes:

- `FULL_COMPATIBLE`
  - same `law_version`
  - no active conflicts
  - all cross-surface requirements satisfied
- `DOWNLEVEL_COMPATIBLE`
  - one side carries extra modules
  - shared modules remain conflict free
  - newer-only modules do not impose unmet requirements on older shared modules
- `INCOMPATIBLE`
  - law version mismatch (without bridge)
  - active conflict
  - unsatisfied requirements

## Compatibility digest

The digest is SHA-256 over canonical JSON of:

- both `law_version` values
- intersection of module IDs with each side's version
- compatibility class

This digest is the signed contract identifier for federation exchange events.

## Negotiation state machine

States:

1. `INIT`
2. `MANIFEST_EXCHANGED`
3. `EVALUATED`
4. `AGREED`
5. `BOUND`
6. `REJECTED`

Deterministic rule:

- if both sides compute the same class and digest and class is `FULL_COMPATIBLE` or `DOWNLEVEL_COMPATIBLE` => `BOUND`
- otherwise => `REJECTED`

Every lineage or mutation bundle exchanged across nodes should carry the bound `compat_digest`.


## Law Evolution Certificates (LECs)

Founders Law v2 now includes certificate primitives in `runtime/governance/law_evolution_certificate.py`.

A certificate binds law change events to epoch transitions with deterministic IDs and digest anchoring:

- `old_manifest_digest`
- `new_manifest_digest`
- `old_epoch_id`
- `new_epoch_id`
- `reason`
- `replay_safe`
- signer metadata + signature

Validation checks enforce:

- old/new manifest digests match supplied manifests
- old/new epoch ids match supplied manifests
- digest pair reflects an actual law change (no no-op)
- deterministic certificate ID integrity
- required signer key id and non-empty signature
- optional replay-safe requirement for strict promotion flows


## Epoch transition binding

Epoch transitions can now bind law evolution metadata through `EpochManager.rotate_epoch(...)`:

- if law surface changes between old/new manifests, a valid Law Evolution Certificate is required
- strict flows can require `replay_safe=true` on the certificate
- new epoch metadata is anchored with:
  - `law_surface_digest`
  - `law_trust_mode`
  - `law_evolution_certificate_id` (when provided)

This makes law changes first-class, auditable epoch transition events.
