#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate governance schema files against repository conventions."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.governance.schema_validator import validate_governance_schemas


def main() -> int:
    errors = validate_governance_schemas()
    if not errors:
        print("governance_schema_validation:ok")
        return 0

    print("governance_schema_validation:failed")
    for schema_path, schema_errors in sorted(errors.items()):
        for error in schema_errors:
            print(f"- {schema_path}: {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
