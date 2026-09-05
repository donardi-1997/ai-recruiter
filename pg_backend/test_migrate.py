"""Tests for DynamoDB → PostgreSQL migration script.

Run:  python -m pytest pg_backend/test_migrate.py -v
"""

import csv
import io
import json

import pytest

from pg_backend.migrate_dynamo_to_pg import (
    normalize_dynamo_value,
    normalize_dynamo_item,
    normalize_candidates,
    normalize_evaluations,
    normalize_jobs,
    normalize_job_candidates,
    normalize_rankings,
    build_copy_buffer,
    _pg_string,
    _json_dumps,
    TABLE_COLUMNS,
)


# ============================================================
# DYNAMODB NORMALIZER
# ============================================================

def test_normalize_string():
    assert normalize_dynamo_value({"S": "hello"}) == "hello"


def test_normalize_number_int():
    assert normalize_dynamo_value({"N": "42"}) == 42


def test_normalize_number_float():
    assert normalize_dynamo_value({"N": "3.14"}) == 3.14


def test_normalize_bool_true():
    assert normalize_dynamo_value({"BOOL": True}) is True


def test_normalize_bool_false():
    assert normalize_dynamo_value({"BOOL": False}) is False


def test_normalize_null():
    assert normalize_dynamo_value({"NULL": True}) is None


def test_normalize_string_set():
    result = normalize_dynamo_value({"SS": ["a", "b", "c"]})
    assert result == ["a", "b", "c"]


def test_normalize_number_set():
    result = normalize_dynamo_value({"NS": ["1", "2", "3"]})
    assert result == [1, 2, 3]


def test_normalize_list():
    dynamo = {"L": [{"S": "x"}, {"N": "10"}]}
    assert normalize_dynamo_value(dynamo) == ["x", 10]


def test_normalize_map():
    dynamo = {"M": {"name": {"S": "Ana"}, "age": {"N": "30"}}}
    result = normalize_dynamo_value(dynamo)
    assert result == {"name": "Ana", "age": 30}


def test_normalize_nested():
    dynamo = {
        "M": {
            "requirements": {
                "L": [
                    {"M": {"requirement": {"S": "Python"}, "status": {"S": "MATCH"}}}
                ]
            }
        }
    }
    result = normalize_dynamo_value(dynamo)
    assert result == {
        "requirements": [{"requirement": "Python", "status": "MATCH"}]
    }


def test_normalize_dynamo_item():
    item = {
        "candidate_id": {"S": "c-001"},
        "name": {"S": "Ana"},
        "indexed": {"BOOL": False},
    }
    result = normalize_dynamo_item(item)
    assert result == {"candidate_id": "c-001", "name": "Ana", "indexed": False}


# ============================================================
# PER-TABLE NORMALIZERS
# ============================================================

def test_normalize_candidates():
    items = [
        {
            "candidate_id": {"S": "c-001"},
            "owner_id": {"S": "user-1"},
            "name": {"S": "Ana García"},
            "filename": {"S": "cv.pdf"},
            "s3_location": {"S": "s3://b/cv.pdf"},
            "indexed": {"BOOL": True},
        }
    ]
    result = normalize_candidates(items)
    assert len(result) == 1
    assert result[0]["candidate_id"] == "c-001"
    assert result[0]["name"] == "Ana García"
    assert result[0]["indexed"] is True


def test_normalize_candidates_falls_back_to_user_sub():
    items = [
        {
            "candidate_id": {"S": "c-001"},
            "user_sub": {"S": "user-from-sub"},
            "name": {"S": "Test"},
            "filename": {"S": "x.pdf"},
            "s3_location": {"S": "s3://b/x.pdf"},
        }
    ]
    result = normalize_candidates(items)
    assert result[0]["owner_id"] == "user-from-sub"


def test_normalize_jobs():
    items = [
        {
            "job_id": {"S": "j-001"},
            "owner_id": {"S": "user-1"},
            "title": {"S": "Dev Python"},
            "description": {"S": "Buscamos backend"},
        }
    ]
    result = normalize_jobs(items)
    assert result[0]["title"] == "Dev Python"


def test_normalize_evaluations_parses_json_strings():
    items = [
        {
            "job_id": {"S": "j-001"},
            "candidate_id": {"S": "c-001"},
            "owner_id": {"S": "u-1"},
            "match_score": {"N": "85"},
            "recommendation": {"S": "STRONG_MATCH"},
            "requirements": {"S": '[{"requirement":"Python","status":"MATCH"}]'},
            "strengths": {"S": '["Fast learner"]'},
            "gaps": {"S": "[]"},
            "summary": {"S": "Great candidate"},
        }
    ]
    result = normalize_evaluations(items)
    assert result[0]["match_score"] == 85
    assert isinstance(result[0]["requirements"], list)
    assert result[0]["requirements"][0]["requirement"] == "Python"
    assert result[0]["strengths"] == ["Fast learner"]
    assert result[0]["gaps"] == []


def test_normalize_evaluations_handles_already_parsed_json():
    items = [
        {
            "job_id": "j-001",
            "candidate_id": "c-001",
            "owner_id": "u-1",
            "match_score": 90,
            "recommendation": "GOOD_MATCH",
            "requirements": [{"requirement": "AWS", "status": "PARTIAL"}],
            "strengths": [],
            "gaps": [],
            "summary": "",
        }
    ]
    result = normalize_evaluations(items)
    assert result[0]["requirements"][0]["status"] == "PARTIAL"


def test_normalize_job_candidates():
    items = [
        {
            "job_id": {"S": "j-001"},
            "candidate_id": {"S": "c-001"},
            "owner_id": {"S": "u-1"},
            "status": {"S": "PENDING_EVALUATION"},
            "assigned_at": {"S": "2026-01-01T00:00:00+00:00"},
        }
    ]
    result = normalize_job_candidates(items)
    assert result[0]["assigned_at"] == "2026-01-01T00:00:00+00:00"


def test_normalize_rankings():
    items = [
        {
            "job_id": {"S": "j-001"},
            "ranking_generated_at": {"S": "2026-09-01T12:00:00+00:00"},
            "ranking_version": {"N": "5"},
        }
    ]
    result = normalize_rankings(items)
    assert result[0]["ranking_version"] == 5


# ============================================================
# COPY BUFFER BUILDER
# ============================================================

def test_pg_string_none():
    assert _pg_string(None) == "\\N"


def test_pg_string_escapes():
    result = _pg_string("line1\nline2\ttab\\back")
    assert "\\n" in result
    assert "\\t" in result
    assert "\\\\" in result


def test_json_dumps_none():
    assert _json_dumps(None) == "\\N"


def test_json_dumps_list():
    result = _json_dumps(["a", "b"])
    assert json.loads(result) == ["a", "b"]


def test_build_copy_buffer():
    columns = ["id", "name", "data"]
    rows = [
        {"id": 1, "name": "Ana", "data": {"key": "val"}},
        {"id": 2, "name": "Bob", "data": None},
    ]
    buf = build_copy_buffer("test_table", columns, rows, jsonb_columns={"data"})
    reader = csv.reader(buf, delimiter="\t")
    lines = list(reader)
    assert len(lines) == 2
    assert lines[0][0] == "1"
    assert lines[0][1] == "Ana"
    # data is JSON-serialized
    assert json.loads(lines[0][2]) == {"key": "val"}
    # None becomes \N
    assert lines[1][2] == "\\N"


# ============================================================
# COLUMN MAPPINGS EXIST
# ============================================================

def test_all_tables_have_column_mappings():
    expected = [
        "REEMPLAZAR_DB_TABLE_CANDIDATES",
        "REEMPLAZAR_DB_TABLE_JOBS",
        "REEMPLAZAR_DB_TABLE_EVALUATIONS",
        "REEMPLAZAR_DB_TABLE_JOB_CANDIDATES",
        "REEMPLAZAR_DB_TABLE_RANKINGS",
    ]
    for table in expected:
        assert table in TABLE_COLUMNS, f"Missing column mapping for {table}"
        assert len(TABLE_COLUMNS[table]) > 0, f"Empty columns for {table}"


def test_evaluations_columns_include_jsonb():
    eval_cols = TABLE_COLUMNS["REEMPLAZAR_DB_TABLE_EVALUATIONS"]
    assert "requirements" in eval_cols
    assert "strengths" in eval_cols
    assert "gaps" in eval_cols
