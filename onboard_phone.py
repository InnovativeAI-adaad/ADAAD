#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
ADAAD Phone Onboarder
---------------------
Optimised for armv8l (32-bit ARM) Termux on Android.

Installs from requirements.phone.txt — pydantic v1, no Rust compilation.
Sets up the environment for running the governance dashboard on port 8000.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQ_PHONE = ROOT / "requirements.phone.txt"
VENV = ROOT / ".venv"
ENV_FILE = Path.home() / ".adaad_phone.env"

_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_CYAN = "\033[96m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _ok(msg: str) -> None:
    print(f"  {_GREEN}✔{_RESET}  {msg}")


def _info(msg: str) -> None:
    print(f"  {_CYAN}→{_RESET}  {msg}")


def _warn(msg: str) -> None:
    print(f"  {_YELLOW}⚠{_RESET}  {msg}")


def _err(msg: str) -> None:
    print(f"  {_RED}✘{_RESET}  {msg}")


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, **kwargs)


def _run_quiet(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Architecture check
# ---------------------------------------------------------------------------

def step_arch_check() -> None:
    arch = platform.machine()
    py = sys.version.split()[0]
    system = platform.system()
    _ok(f"Python {py} · {arch} · {system}")
    if arch not in ("armv8l", "armv7l", "aarch64"):
        _warn(f"Unexpected architecture: {arch}")
        _warn("This onboarder is optimised for armv8l (32-bit ARM Termux).")
        _warn("For desktop/server, use:  python onboard.py")


# ---------------------------------------------------------------------------
# System dependency check
# ---------------------------------------------------------------------------

def step_system_deps() -> None:
    missing = []
    for pkg in ("libsodium",):
        path = shutil.which("pkg")
        if path:
            r = _run_quiet(["pkg", "list-installed"])
            if pkg not in (r.stdout or ""):
                missing.append(pkg)

    # Check if nacl is importable
    r = _run_quiet([sys.executable, "-c", "import nacl"])
    if r.returncode != 0:
        _warn("PyNaCl not found. Ed25519 replay attestation will use fallback.")
        _info("To install:  pkg install python-nacl")
    else:
        _ok("PyNaCl available (Ed25519 attestation enabled)")


# ---------------------------------------------------------------------------
# Virtual environment
# ---------------------------------------------------------------------------

def _venv_python() -> str:
    for candidate in (VENV / "bin" / "python3", VENV / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def step_venv() -> None:
    if VENV.exists() and (VENV / "bin" / "python3").exists():
        _ok("Virtual environment found (.venv)")
        return
    _info("Creating virtual environment (.venv)…")
    r = _run([sys.executable, "-m", "venv", str(VENV)], capture_output=True, text=True)
    if r.returncode != 0:
        _warn("venv creation failed — will use system Python directly.")
        _warn(r.stderr[-200:] if r.stderr else "")
        return
    _ok("Virtual environment created (.venv)")


# ---------------------------------------------------------------------------
# Install phone-safe dependencies
# ---------------------------------------------------------------------------

def step_install() -> None:
    if not REQ_PHONE.exists():
        _err(f"requirements.phone.txt not found at {REQ_PHONE}")
        sys.exit(1)

    _info("Installing phone-safe dependencies…")
    _info("(pydantic v1, no Rust compilation — safe for armv8l)")

    python = _venv_python()
    r = _run_quiet([
        python, "-m", "pip", "install",
        "-r", str(REQ_PHONE),
        "--only-binary", ":all:",
        "--prefer-binary",
        "--quiet",
    ])
    if r.returncode != 0:
        # Retry without --only-binary for pure-Python packages that have no wheels
        _warn("Binary-only install had issues — retrying without wheel restriction for pure-Python packages…")
        r2 = _run_quiet([
            python, "-m", "pip", "install",
            "-r", str(REQ_PHONE),
            "--prefer-binary",
            "--quiet",
        ])
        if r2.returncode != 0:
            _err("Dependency install failed.")
            print(r2.stderr[-600:] if r2.stderr else "")
            _warn("Try manually:  pip install -r requirements.phone.txt --prefer-binary")
            sys.exit(1)

    # Quick verify
    python = _venv_python()
    check = _run_quiet([python, "-c", "import fastapi; print(fastapi.__version__)"])
    if check.returncode == 0:
        _ok(f"fastapi {check.stdout.strip()} installed")
    else:
        _err("fastapi not importable after install — check errors above.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Soulbound key
# ---------------------------------------------------------------------------

def _ensure_soulbound_key() -> str:
    """Return the soulbound key, generating and persisting one if absent."""
    existing = os.environ.get("ADAAD_SOULBOUND_KEY", "").strip()
    if existing:
        return existing

    # Check persisted key
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("ADAAD_SOULBOUND_KEY="):
                key = line.split("=", 1)[1].strip().strip('"')
                if key:
                    return key

    # Generate fresh key
    import secrets
    key = secrets.token_hex(32)
    try:
        existing_lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
        other_lines = [l for l in existing_lines if not l.startswith("ADAAD_SOULBOUND_KEY=")]
        ENV_FILE.write_text("\n".join(other_lines + [f'ADAAD_SOULBOUND_KEY="{key}"']) + "\n")
    except OSError:
        pass
    return key


def step_env() -> None:
    key = _ensure_soulbound_key()
    masked = key[:8] + "…" + key[-4:]
    _ok(f"ADAAD_SOULBOUND_KEY={masked}  (saved to ~/.adaad_phone.env)")
    _ok("ADAAD_ENV=dev")
    _ok("CRYOVANT_DEV_MODE=1")

    # Write the start script
    start_script = ROOT / "start_phone.sh"
    start_script.write_text(
        "#!/usr/bin/env bash\n"
        "# ADAAD phone start — generated by onboard_phone.py\n"
        "# Run this to start the governance dashboard.\n"
        'cd "$(dirname "$0")"\n'
        "\n"
        "# Load persisted env\n"
        '[ -f ~/.adaad_phone.env ] && source ~/.adaad_phone.env\n'
        "\n"
        "export ADAAD_ENV=dev\n"
        "export CRYOVANT_DEV_MODE=1\n"
        f'export ADAAD_SOULBOUND_KEY="${{ADAAD_SOULBOUND_KEY:-{key}}}"\n'
        "\n"
        "source .venv/bin/activate 2>/dev/null || true\n"
        "\n"
        "echo ''\n"
        "echo '  ADAAD governance dashboard'\n"
        "echo '  Open in Chrome: http://127.0.0.1:8000'\n"
        "echo '  Press Ctrl+C to stop.'\n"
        "echo ''\n"
        "\n"
        "uvicorn server:app --host 127.0.0.1 --port 8000\n"
    )
    try:
        start_script.chmod(0o755)
    except OSError:
        pass
    _ok("start_phone.sh written")


# ---------------------------------------------------------------------------
# Workspace init
# ---------------------------------------------------------------------------

def step_workspace() -> None:
    python = _venv_python()
    r = _run_quiet([python, "nexus_setup.py"])
    if r.returncode == 0:
        _ok("Workspace initialised")
    else:
        _warn("Workspace init had warnings (non-fatal).")


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def step_schemas() -> None:
    schema_script = ROOT / "scripts" / "validate_governance_schemas.py"
    if not schema_script.exists():
        _warn("Schema validation script not found — skipping.")
        return
    python = _venv_python()
    r = _run_quiet([python, str(schema_script)])
    if r.returncode == 0:
        _ok("Governance schemas valid")
    else:
        _warn("Schema validation warnings (non-fatal).")


# ---------------------------------------------------------------------------
# Connectivity test
# ---------------------------------------------------------------------------

def step_verify() -> None:
    python = _venv_python()
    r = _run_quiet([python, "-c", """
import fastapi, uvicorn, starlette, pydantic, httpx, yaml
print(f"fastapi={fastapi.__version__} pydantic={pydantic.VERSION} uvicorn={uvicorn.__version__}")
"""])
    if r.returncode == 0:
        _ok(f"Import check: {r.stdout.strip()}")
    else:
        _err("Import check failed.")
        print(r.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print()
    print(f"  {_BOLD}ADAAD{_RESET}  Phone Setup")
    print(f"  Optimised for armv8l · Termux · Android")
    print(f"  {'─' * 44}")
    print()

    _info("Checking architecture…")
    step_arch_check()

    _info("Checking system packages…")
    step_system_deps()

    _info("Setting up virtual environment…")
    step_venv()

    _info("Installing phone-safe dependencies…")
    step_install()

    _info("Configuring environment…")
    step_env()

    _info("Initialising workspace…")
    step_workspace()

    _info("Validating governance schemas…")
    step_schemas()

    _info("Verifying imports…")
    step_verify()

    print()
    print(f"  {'━' * 50}")
    print(f"  {_BOLD}{_GREEN}ADAAD is ready.{_RESET}")
    print()
    print(f"  Start the dashboard:")
    print(f"    {_CYAN}bash start_phone.sh{_RESET}")
    print()
    print(f"  Then open Chrome:   {_BOLD}http://127.0.0.1:8000{_RESET}")
    print()
    print(f"  {_YELLOW}Note:{_RESET} AI epoch execution (python -m app.main) requires")
    print(f"  the anthropic package. On armv8l this may not install.")
    print(f"  The governance dashboard works fully without it.")
    print(f"  {'━' * 50}")
    print()


if __name__ == "__main__":
    main()
