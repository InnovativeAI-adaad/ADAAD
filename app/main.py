from __future__ import annotations

import os
from pathlib import Path
# Normalize cwd to repo root so relative paths resolve correctly
os.chdir(Path(__file__).resolve().parents[1])

from runtime.boot import boot_sequence
from runtime.logger import get_logger


def main() -> dict:
    logger = get_logger(component="boot")
    logger.info("boot start")
    try:
        status = boot_sequence()
        outcome = "ok" if status.get("structure_ok", False) else "error"
        logger.audit("boot", actor="system", outcome=outcome, status=status)
        return status
    except Exception as exc:  # pragma: no cover - defensive boot guard
        logger.audit("boot", actor="system", outcome="error", error=str(exc))
        raise


if __name__ == "__main__":
    main()
