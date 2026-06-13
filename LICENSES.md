# Licensing Overview

- **Repository license**: Proprietary Software License (see `LICENSE`).
- **Prior releases**: Versions that were distributed under Apache License 2.0 remain governed by Apache-2.0 for recipients who received those versions before the license change.
- **Python source headers**: Repository-authored Python source files use the exact `# SPDX-License-Identifier: Apache-2.0` header as the governed source-header invariant. This header policy is enforced separately from the current proprietary repository distribution license.
- **Documentation, examples, tests, tools, and scripts**: Proprietary unless another in-file notice states otherwise; Python files still follow the exact Apache-2.0 SPDX source-header invariant.

## 2026-06-13 licensing decision

After review of the root `LICENSE`, ADAAD keeps the current proprietary repository license and does **not** add Commons Clause. No Apache-2.0 + Commons Clause open-core subset is created in this change because no module/path boundary has been ratified for open-core distribution.

Current applicability remains:

- `LICENSE` applies to the repository as a whole from the versions identified in that file.
- No `LICENSE.open-core` or `LICENSE.enterprise` file is authoritative unless added by a future governed change with an explicit path/module classification table.
- Python `# SPDX-License-Identifier: Apache-2.0` headers remain a source-header compliance invariant only; they do not relicense the active repository distribution.
- Any future open-core proposal must classify every affected module path before license text changes, and must preserve patent, trademark, HUMAN-0, and governance restrictions unless separately ratified.

## Third-party dependencies

Third-party packages retain their own licenses. Review dependency manifests and
upstream project notices before redistribution in regulated environments.


## License compatibility quick matrix

| Dependency license family | Compatibility with ADAAD proprietary distribution | Notes |
| --- | --- | --- |
| MIT / BSD / ISC | Case-by-case review required | Preserve notices and attribution where required. |
| Apache-2.0 | Case-by-case review required | Preserve NOTICE/attribution obligations where required. |
| GPL / AGPL / copyleft | Legal review required | Do not redistribute in regulated releases without counsel approval. |

## Compliance automation

Run `python scripts/validate_license_compliance.py` in CI to verify proprietary
license artifacts and exact Apache-2.0 Python SPDX/header guardrails.

## Documentation image provenance and brand constraints

- Image provenance manifest: `docs/assets/IMAGE_PROVENANCE.md`.
- All current `docs/assets/` images are repository-authored; no third-party image license is currently recorded.
- ADAAD brand visuals and marks remain trademark-restricted; see `BRAND_LICENSE.md` and filename-level notes in the image manifest before reuse outside repository docs/releases.
