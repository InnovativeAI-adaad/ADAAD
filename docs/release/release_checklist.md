# Release Checklist

Use this checklist for any release candidate, with strict enforcement for governance/public-readiness milestones.

## 1) Build and quality gates

- [ ] CI required checks are green for the release commit.
- [ ] Determinism and governance test suites passed on the release commit.
- [ ] CodeQL workflow is green for the release commit/PR.

## 2) Evidence completeness gate (announcement blocker)

- [ ] `docs/comms/claims_evidence_matrix.md` is updated for this release scope.
- [ ] All required claim rows are marked `Complete` with objective evidence links.
- [ ] `python scripts/validate_release_evidence.py --require-complete` passes.

> **Hard block:** Do not publish public release notes, governance milestone updates, roadmap posts, or social announcements until every evidence entry above is complete and validated.

## 3) Versioned documentation and release notes

- [ ] Release notes file exists under `docs/releases/` and reflects scope.
- [ ] Governance/spec deltas are reflected in versioned docs.
- [ ] Any externally referenced docs/spec links are immutable/versioned.

## 4) Tagging controls for governance/public-readiness releases

- [ ] For milestone tags (e.g., `vX.Y.Z-governance-*` / `vX.Y.Z-public-readiness-*`), confirm `.github/workflows/release_evidence_gate.yml` passed.
- [ ] Only create/publish the tag after evidence gate checks pass.
