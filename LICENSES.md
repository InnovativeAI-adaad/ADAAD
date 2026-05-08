# Licensing Overview

- **Repository license**: Proprietary Software License (see `LICENSE`).
- **Prior releases**: Versions that were distributed under Apache License 2.0 remain governed by Apache-2.0 for recipients who received those versions before the license change.
- **Python source headers**: Repository-authored Python source files use the exact `# SPDX-License-Identifier: Apache-2.0` header as the governed source-header invariant. This header policy is enforced separately from the current proprietary repository distribution license.
- **Documentation, examples, tests, tools, and scripts**: Proprietary unless another in-file notice states otherwise; Python files still follow the exact Apache-2.0 SPDX source-header invariant.

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
