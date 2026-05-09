# SPDX-License-Identifier: Apache-2.0
"""
tests/test_phase174_compliance_fix.py — Phase 174 · Compliance Module Fix
Validates COMPLIANCE-CONST-0, COMPLIANCE-STREAM-0, COMPLIANCE-DATA-0

Test IDs: T174-CMF-01 through T174-CMF-30
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.api.compliance import (
    _COMPLIANCE_EXPORT_LIMIT_DEFAULT,
    _COMPLIANCE_EXPORT_LIMIT_MAX,
    _jsonable_scalar,
    compliance_dataset_rows,
    stream_csv_rows,
    stream_json_records,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_rows() -> list[dict[str, Any]]:
    return [
        {"id": "r1", "score": 0.9, "phase": 174, "flag": True},
        {"id": "r2", "score": 0.5, "phase": 174, "flag": False},
        {"id": "r3", "score": 0.1, "phase": 174, "flag": None},
    ]


@pytest.fixture
def empty_rows() -> list[dict[str, Any]]:
    return []


# ── T174-CMF-01: constants are defined ───────────────────────────────────────

def test_limit_default_defined():  # T174-CMF-01
    assert _COMPLIANCE_EXPORT_LIMIT_DEFAULT is not None


def test_limit_default_positive():  # T174-CMF-02
    assert _COMPLIANCE_EXPORT_LIMIT_DEFAULT > 0


def test_limit_max_defined():  # T174-CMF-03
    assert _COMPLIANCE_EXPORT_LIMIT_MAX is not None


def test_limit_max_positive():  # T174-CMF-04
    assert _COMPLIANCE_EXPORT_LIMIT_MAX > 0


def test_limit_default_le_max():  # T174-CMF-05
    assert _COMPLIANCE_EXPORT_LIMIT_DEFAULT <= _COMPLIANCE_EXPORT_LIMIT_MAX


def test_limit_default_value():  # T174-CMF-06
    assert _COMPLIANCE_EXPORT_LIMIT_DEFAULT == 200


def test_limit_max_value():  # T174-CMF-07
    assert _COMPLIANCE_EXPORT_LIMIT_MAX == 1000


# ── T174-CMF-08: _jsonable_scalar ────────────────────────────────────────────

def test_scalar_str():  # T174-CMF-08
    assert _jsonable_scalar("hello") == "hello"


def test_scalar_int():  # T174-CMF-09
    assert _jsonable_scalar(42) == 42


def test_scalar_float():  # T174-CMF-10
    assert _jsonable_scalar(3.14) == 3.14


def test_scalar_bool():  # T174-CMF-11
    assert _jsonable_scalar(True) is True


def test_scalar_none():  # T174-CMF-12
    assert _jsonable_scalar(None) is None


def test_scalar_dict_serialized():  # T174-CMF-13
    result = _jsonable_scalar({"a": 1})
    assert isinstance(result, str)
    assert json.loads(result) == {"a": 1}


# ── T174-CMF-14: stream_csv_rows ─────────────────────────────────────────────

def test_csv_empty_yields_nothing(empty_rows):  # T174-CMF-14
    chunks = list(stream_csv_rows(empty_rows))
    assert chunks == []


def test_csv_yields_header(sample_rows):  # T174-CMF-15
    chunks = list(stream_csv_rows(sample_rows))
    header = chunks[0]
    assert "id" in header and "score" in header


def test_csv_row_count(sample_rows):  # T174-CMF-16
    chunks = list(stream_csv_rows(sample_rows))
    # 1 header + 3 data rows
    assert len(chunks) == 4


def test_csv_all_strings(sample_rows):  # T174-CMF-17
    for chunk in stream_csv_rows(sample_rows):
        assert isinstance(chunk, str)


def test_csv_parseable(sample_rows):  # T174-CMF-18
    combined = "".join(stream_csv_rows(sample_rows))
    reader = csv.DictReader(io.StringIO(combined))
    rows = list(reader)
    assert len(rows) == 3


def test_csv_id_values(sample_rows):  # T174-CMF-19
    combined = "".join(stream_csv_rows(sample_rows))
    reader = csv.DictReader(io.StringIO(combined))
    ids = [r["id"] for r in reader]
    assert "r1" in ids and "r2" in ids and "r3" in ids


def test_csv_sorted_keys(sample_rows):  # T174-CMF-20
    header_chunk = next(stream_csv_rows(sample_rows))
    first_line = header_chunk.strip()
    keys = first_line.split(",")
    assert keys == sorted(keys)


# ── T174-CMF-21: stream_json_records ─────────────────────────────────────────

def test_json_output_valid(sample_rows):  # T174-CMF-21
    envelope = {"schema_version": "1.1", "data": {"dataset": "test"}}
    combined = "".join(stream_json_records(envelope=envelope, rows=sample_rows))
    obj = json.loads(combined)
    assert isinstance(obj, dict)


def test_json_has_records_key(sample_rows):  # T174-CMF-22
    envelope = {"data": {}}
    combined = "".join(stream_json_records(envelope=envelope, rows=sample_rows))
    obj = json.loads(combined)
    assert "records" in obj


def test_json_record_count(sample_rows):  # T174-CMF-23
    envelope = {"data": {}}
    combined = "".join(stream_json_records(envelope=envelope, rows=sample_rows))
    obj = json.loads(combined)
    assert len(obj["records"]) == 3


def test_json_empty_rows(empty_rows):  # T174-CMF-24
    envelope = {"data": {}}
    combined = "".join(stream_json_records(envelope=envelope, rows=empty_rows))
    obj = json.loads(combined)
    assert obj["records"] == []


def test_json_preserves_envelope_keys(sample_rows):  # T174-CMF-25
    envelope = {"schema_version": "1.1", "data": {"dataset": "test"}}
    combined = "".join(stream_json_records(envelope=envelope, rows=sample_rows))
    obj = json.loads(combined)
    assert obj.get("schema_version") == "1.1"


def test_json_data_section_present(sample_rows):  # T174-CMF-26
    envelope = {"data": {"dataset": "test-ds"}}
    combined = "".join(stream_json_records(envelope=envelope, rows=sample_rows))
    obj = json.loads(combined)
    assert obj["data"]["dataset"] == "test-ds"


def test_json_records_not_in_data(sample_rows):  # T174-CMF-27
    envelope = {"data": {"records": ["should_be_removed"]}}
    combined = "".join(stream_json_records(envelope=envelope, rows=sample_rows))
    obj = json.loads(combined)
    # records must be at root, not nested under data
    assert "records" not in obj.get("data", {})
    assert "records" in obj


# ── T174-CMF-28: import guard ────────────────────────────────────────────────

def test_module_imports_without_error():  # T174-CMF-28
    import app.api.compliance  # noqa: F401  — must not raise NameError
    assert True


def test_router_is_apirouter():  # T174-CMF-29
    from app.api.compliance import router
    from fastapi import APIRouter
    assert isinstance(router, APIRouter)


def test_constants_are_int():  # T174-CMF-30
    assert isinstance(_COMPLIANCE_EXPORT_LIMIT_DEFAULT, int)
    assert isinstance(_COMPLIANCE_EXPORT_LIMIT_MAX, int)
