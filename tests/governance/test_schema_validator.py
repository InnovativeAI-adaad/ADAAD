from __future__ import annotations

from runtime.governance.schema_validator import validate_governance_schemas


def test_validate_governance_schemas_reports_no_errors_for_repo_schemas() -> None:
    assert validate_governance_schemas() == {}
