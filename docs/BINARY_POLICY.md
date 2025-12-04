# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
# Binary artifact policy and troubleshooting

This project blocks unchecked binary artifacts to keep Cryovant integrity and the mutation engine auditable. If you encounter a `binary not allowed` error when pushing from a system such as `codex`, follow these steps:

1. Identify the file flagged as binary (e.g., `git status`, `git diff --cached`).
2. If it should not be tracked, remove it from the index while keeping the local copy:
   ```
   git rm --cached <path-to-file>
   ```
3. Add an ignore rule in `.gitignore` so the file is never staged again (e.g., `*.db`, `*.zip`, `*.tar.gz`, `*.tgz`).
4. Commit the removal and push again.

If a binary must be kept for releases, use a reviewed storage mechanism (such as an approved artifact bucket or LFS policy) instead of committing it directly.
