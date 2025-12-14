from __future__ import annotations

import json
from pathlib import Path
from typing import Tuple


REQUIRED_SCHEMAS = {
    "dna.json": "he65.agent.dna.v1",
    "certificate.json": "he65.agent.cert.v1",
}


def validate_agent_contract(agent_dir: Path) -> Tuple[bool, list[str]]:
    """
    Validate that an agent directory contains the required contract files and schemas.
    Returns (is_valid, reasons).
    """

    errors: list[str] = []
    base = Path(agent_dir)

    meta_path = base / "meta.json"
    if not meta_path.exists():
        errors.append("meta_missing")
    else:
        try:
            json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive logging path
            errors.append(f"meta_invalid:{exc}")

    for filename, required_schema in REQUIRED_SCHEMAS.items():
        path = base / filename
        if not path.exists():
            errors.append(f"{filename}_missing")
            continue

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive logging path
            errors.append(f"{filename}_invalid:{exc}")
            continue

        if data.get("$schema") != required_schema:
            errors.append(f"{filename}_schema_mismatch")

    return len(errors) == 0, errors


__all__ = ["validate_agent_contract", "REQUIRED_SCHEMAS"]
