# Release Ops Handoff — Signed Tag Ceremony for v9.93.0

## Scope

This handoff artifact defines the **exact** release-tag ceremony for:

- **Tag:** `v9.93.0`

It follows prior ADAAD governance guidance for signed-tag controls and legal/evidence continuity tied to **FINDING-66-003**:

- `docs/governance/AUDIT_CLOSEOUT_REPORT_2026-03.md` (signed-tag verification evidence and HUMAN-0 operator constraints)
- `docs/governance/V1_GA_READINESS_CHECKLIST.md` (GPG tag ceremony command pattern and gating expectations)
- `docs/IP_PATENT_FILING_ARTIFACT.md` (finding closure chain for FINDING-66-003)

## Preconditions (fail-closed)

1. Operator is on the intended release commit SHA (do **not** tag an unverified branch tip).
2. Founder/HUMAN-0 signing key is available in local GPG keyring.
3. `origin` remote is configured for push.

Recommended pre-checks:

```bash
git rev-parse --verify HEAD
git remote -v
gpg --list-secret-keys --keyid-format LONG
```

## Signed tag command sequence (exact tag: v9.93.0)

> Replace `<RELEASE_SHA>` only if you are intentionally tagging a non-HEAD verified release commit.

```bash
# 1) Sync and verify target commit context
git fetch --tags origin

# 2) Optional explicit checkout to release SHA
git checkout <RELEASE_SHA>

# 3) Create signed annotated tag
git tag -s v9.93.0 \
  -m "v9.93.0 — governed release tag ceremony (FINDING-66-003 evidence continuity)"

# 4) Push tag to origin
git push origin v9.93.0
```

## Verification steps (required)

### A) Local signature verification

```bash
git tag -v v9.93.0
```

Expected outcome:
- GPG reports a **Good signature** from the expected HUMAN-0 identity/key.

### B) Remote tag presence verification

Use both checks:

```bash
# Verify remote exposes tag ref
git ls-remote --tags origin | grep "refs/tags/v9.93.0$"

# Verify local metadata points to pushed tag object
git show v9.93.0 --no-patch --pretty=fuller
```

Expected outcome:
- `refs/tags/v9.93.0` exists on `origin`.
- Tag metadata/signature output matches local verified tag.

## Rollback / remediation if signature verification fails

If `git tag -v v9.93.0` fails at any point, treat as a **hard stop**.

1. **Do not proceed with release promotion.**
2. Capture failure output in operator evidence notes.
3. Remove incorrect local tag:

```bash
git tag -d v9.93.0
```

4. If a bad/unsigned tag was pushed, delete remote tag immediately:

```bash
git push --delete origin v9.93.0
```

5. Remediate root cause, then re-run ceremony:
   - wrong signing key selected → set explicit key (`git config user.signingkey <KEYID>`)
   - missing secret key on workstation → import/restore founder key material per ceremony policy
   - wrong commit tagged → checkout verified `<RELEASE_SHA>` and recreate signed tag
   - stale local/remote refs → `git fetch --tags --prune origin` and retry

6. Re-run required verification:

```bash
git tag -v v9.93.0
git ls-remote --tags origin | grep "refs/tags/v9.93.0$"
```

Release remains blocked until both checks pass.
