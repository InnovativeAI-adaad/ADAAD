# SPDX-License-Identifier: Apache-2.0
"""
ADAAD Codex Preflight Stub
[INV-PREFLIGHT] — bootstraps contract validation until
scripts/preflight.py is registered and promoted.

Checks (fail-closed on each):
  1. Python 3.11 pinned runtime
  2. CONSTITUTION_VERSION env var or file present
  3. Core src/ module importable
  4. No .pyc-only distribution (source must be present)
"""
import sys
import os
import pathlib

FAILURES: list[str] = []

def check(condition: bool, code: str, msg: str) -> None:
    if not condition:
        FAILURES.append(f"[PREFLIGHT-FAIL][{code}] {msg}")

# ── 1. Runtime pin ─────────────────────────────────────────
check(
    sys.version_info[:2] == (3, 11),
    "INV-RUNTIME",
    f"Python 3.11 required; active={sys.version_info[:2]}"
)

# ── 2. CONSTITUTION_VERSION ────────────────────────────────
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CONST_FILE = REPO_ROOT / "CONSTITUTION_VERSION"
CONST_ENV  = os.environ.get("CONSTITUTION_VERSION")

check(
    CONST_FILE.exists() or bool(CONST_ENV),
    "INV-CONSTITUTION",
    "CONSTITUTION_VERSION file or env var must be present before execution"
)

# ── 3. Core module importability ───────────────────────────
src_init = REPO_ROOT / "src" / "__init__.py"
check(
    src_init.exists(),
    "INV-SRC",
    "src/__init__.py absent — source tree not intact"
)

# ── 4. Source-present guard ────────────────────────────────
pyc_only = list(REPO_ROOT.rglob("*.pyc")) and not list(REPO_ROOT.rglob("*.py"))
check(not pyc_only, "INV-SOURCE", ".pyc-only distribution detected — source required")

# ── Emit result ────────────────────────────────────────────
if FAILURES:
    for f in FAILURES:
        print(f, file=sys.stderr)
    print("[PREFLIGHT][FATAL] Contract gate blocked — see failures above", file=sys.stderr)
    sys.exit(1)

print(f"[PREFLIGHT][PASS] All contracts satisfied — {len(FAILURES)} failures")
