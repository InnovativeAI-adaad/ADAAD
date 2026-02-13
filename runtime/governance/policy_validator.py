# SPDX-License-Identifier: Apache-2.0
"""Pre-proposal validation for constitutional policy text."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from runtime.constitution import CONSTITUTION_VERSION, load_constitution_policy


@dataclass
class PolicyValidationResult:
    valid: bool
    errors: list[str]


class PolicyValidator:
    def validate(self, policy_text: str) -> PolicyValidationResult:
        tmp = Path("runtime/governance/.policy_validator_tmp.json")
        try:
            tmp.write_text(policy_text, encoding="utf-8")
            load_constitution_policy(path=tmp, expected_version=CONSTITUTION_VERSION)
            return PolicyValidationResult(valid=True, errors=[])
        except Exception as exc:
            return PolicyValidationResult(valid=False, errors=[str(exc)])
        finally:
            tmp.unlink(missing_ok=True)


__all__ = ["PolicyValidator", "PolicyValidationResult"]
