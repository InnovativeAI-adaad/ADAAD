# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class CmdResult:
    ok: bool
    returncode: int
    duration_ms: int
    stdout_tail: str
    stderr_tail: str


def run_cmd(
    *,
    cmd: List[str],
    cwd: Path,
    timeout_s: float = 30.0,
    env: Optional[Dict[str, str]] = None,
) -> CmdResult:
    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
        dt = int((time.time() - start) * 1000)
        return CmdResult(
            ok=(proc.returncode == 0),
            returncode=proc.returncode,
            duration_ms=dt,
            stdout_tail=(proc.stdout or "")[-6000:],
            stderr_tail=(proc.stderr or "")[-6000:],
        )
    except subprocess.TimeoutExpired as exc:
        dt = int((time.time() - start) * 1000)
        return CmdResult(
            ok=False,
            returncode=124,
            duration_ms=dt,
            stdout_tail="",
            stderr_tail=f"TimeoutExpired: {exc}",
        )


def py_compile_files(repo_root: Path, rel_files: List[str], timeout_s: float = 30.0) -> CmdResult:
    files = [str(repo_root / f) for f in rel_files if f.endswith(".py")]
    if not files:
        return CmdResult(ok=True, returncode=0, duration_ms=0, stdout_tail="", stderr_tail="")
    cmd = [sys.executable, "-m", "py_compile"] + files
    env = {"PYTHONNOUSERSITE": "1"}
    return run_cmd(cmd=cmd, cwd=repo_root, timeout_s=timeout_s, env=env)
