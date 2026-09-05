"""Tests for pg_backend scaffold.

Uses an in-memory SQLite database for isolation.
Run:  python -m pytest pg_backend/tests.py -v
"""

import hashlib

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pg_backend.database import Base, get_db
from pg_backend.models import (
    Candidate,
    Evaluation,
    Job,
    JobCandidate,
    Ranking,
    RankingItem,
)
from pg_backend.crud import (
    _advisory_lock_key,
    acquire_job_lock,
    create_candidate,
    create_job,
    get_candidate,
    get_evaluation,
    get_job,
    get_new_candidate_ids,
    get_ranking_metadata,
    upsert_evaluation,
    upsert_ranking_metadata,
)

import pytest


# ============================================================
# FIXTURES
# ============================================================

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db_session():
    """Yield a fresh database session per test."""
    engine = create_engine(TEST_DB_URL, echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


# ============================================================
# CONSTANTS
# ============================================================

JOB_ID      = "job-001"
OWNER_ID    = "user-abc"
CANDIDATE_1 = "cand-001"
CANDIDATE_2 = "cand-002"
CANDIDATE_3 = "cand-003"


# ============================================================
# TESTS — ADVISORY LOCK KEY
# ============================================================

def test_advisory_lock_key_is_deterministic():
    key_a = _advisory_lock_key(JOB_ID)
    key_b = _advisory_lock_key(JOB_ID)
    assert key_a == key_b


def test_advisory_lock_key_differs_per_job():
    key_1 = _advisory_lock_key("job-001")
    key_2 = _advisory_lock_key("job-002")
    assert key_1 != key_2


def test_advisory_lock_key_is_64bit_signed():
    key = _advisory_lock_key(JOB_ID)
    assert -(2**63) <= key < 2**63


# ============================================================
# TESTS — MODELS READ
# ============================================================

def test_read_ranking_table_constant():
    assert Ranking.__tablename__ == "REEMPLAZAR_DB_TABLE_RANKINGS"


def test_read_ranking_items_table_constant():
    assert RankingItem.__tablename__ == "REEMPLAZAR_DB_TABLE_RANKING_ITEMS"


def test_read_candidates_table_constant():
    assert Candidate.__tablename__ == "REEMPLAZAR_DB_TABLE_CANDIDATES"


def test_read_jobs_table_constant():
    assert Job.__tablename__ == "REEMPLAZAR_DB_TABLE_JOBS"


# ============================================================
# TESTS — CRUD
# ============================================================

def test_create_and_get_job(db_session):
    job = create_job(db_session, JOB_ID, OWNER_ID, "Dev Python", "Buscamos backend senior")
    assert job.job_id == JOB_ID
    assert job.title == "Dev Python"

    fetched = get_job(db_session, JOB_ID)
    assert fetched is not None
    assert fetched.owner_id == OWNER_ID


def test_create_candidate(db_session):
    cand = create_candidate(
        db_session,
        CANDIDATE_1,
        OWNER_ID,
        "Ana García",
        "cv-001.pdf",
        "s3://bucket/cv-001.pdf",
    )
    assert cand.name == "Ana García"

    fetched = get_candidate(db_session, CANDIDATE_1)
    assert fetched is not None
    assert fetched.s3_location == "s3://bucket/cv-001.pdf"


def test_get_nonexistent_job_returns_none(db_session):
    assert get_job(db_session, "does-not-exist") is None


def test_upsert_evaluation_creates(db_session):
    create_job(db_session, JOB_ID, OWNER_ID, "Dev", "Desc")
    create_candidate(db_session, CANDIDATE_1, OWNER_ID, "Ana", "cv.pdf", "s3://x")

    ev = upsert_evaluation(
        db_session,
        JOB_ID,
        CANDIDATE_1,
        OWNER_ID,
        job_title="Dev",
        job_description="Desc",
        candidate_name="Ana",
        match_score=85,
        recommendation="STRONG_MATCH",
        requirements=[],
        strengths=["Python"],
        gaps=["No AWS"],
        summary="Buena candidata",
    )
    assert ev.match_score == 85

    fetched = get_evaluation(db_session, JOB_ID, CANDIDATE_1)
    assert fetched.recommendation == "STRONG_MATCH"


def test_upsert_evaluation_updates_existing(db_session):
    create_job(db_session, JOB_ID, OWNER_ID, "Dev", "Desc")
    create_candidate(db_session, CANDIDATE_1, OWNER_ID, "Ana", "cv.pdf", "s3://x")

    upsert_evaluation(
        db_session, JOB_ID, CANDIDATE_1, OWNER_ID,
        job_title="Dev", job_description="Desc",
        candidate_name="Ana", match_score=50,
        recommendation="LOW_MATCH", requirements=[],
        strengths=[], gaps=[], summary="",
    )
    updated = upsert_evaluation(
        db_session, JOB_ID, CANDIDATE_1, OWNER_ID,
        job_title="Dev", job_description="Desc",
        candidate_name="Ana", match_score=92,
        recommendation="STRONG_MATCH", requirements=[],
        strengths=["Python", "AWS"], gaps=[], summary="Top",
    )
    assert updated.match_score == 92

    fetched = get_evaluation(db_session, JOB_ID, CANDIDATE_1)
    assert fetched.match_score == 92
    assert fetched.recommendation == "STRONG_MATCH"


def test_ranking_metadata_crud(db_session):
    meta = upsert_ranking_metadata(db_session, JOB_ID, 1)
    assert meta.ranking_version == 1

    meta2 = upsert_ranking_metadata(db_session, JOB_ID, 5)
    assert meta2.ranking_version == 5

    fetched = get_ranking_metadata(db_session, JOB_ID)
    assert fetched.ranking_version == 5


def test_get_new_candidate_ids_filters_by_date(db_session):
    """Verify filtering by assigned_at > since works in SQLite."""
    from pg_backend.models import JobCandidate
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)

    # cand-001: assigned 2 hours ago (BEFORE since → should NOT appear)
    db_session.add(JobCandidate(
        job_id=JOB_ID,
        candidate_id=CANDIDATE_1,
        owner_id=OWNER_ID,
        assigned_at=now - timedelta(hours=2),
    ))
    # cand-002: assigned 30 min ago (AFTER since → should appear)
    db_session.add(JobCandidate(
        job_id=JOB_ID,
        candidate_id=CANDIDATE_2,
        owner_id=OWNER_ID,
        assigned_at=now - timedelta(minutes=30),
    ))
    db_session.commit()

    new_ids = get_new_candidate_ids(db_session, JOB_ID, OWNER_ID, one_hour_ago)
    assert CANDIDATE_1 not in new_ids
    assert CANDIDATE_2 in new_ids
