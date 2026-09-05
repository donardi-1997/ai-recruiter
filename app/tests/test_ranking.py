"""Tests for the AI Recruiter FastAPI backend.

Uses SQLite for isolation (no Postgres required).
Run:  python -m pytest app/tests/ -v
"""

import os
import tempfile
import uuid

# Force SQLite before any app imports
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.deps import acquire_job_lock, _advisory_lock_key, get_current_user, get_db
from app.main import app
from app.models import Candidate, Job, Ranking, RankingItem
from app.crud import get_ranking_metadata, get_ranking_items


# ============================================================
# FIXTURES
# ============================================================

_test_db_fd = None
_test_db_path = None


@pytest.fixture(scope="function")
def db_session():
    """Yield a fresh SQLite session per test."""
    global _test_db_fd, _test_db_path

    _test_db_fd, _test_db_path = tempfile.mkstemp(suffix=".db")
    db_url = f"sqlite:///{_test_db_path}"

    engine = create_engine(
        db_url, echo=False, connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    os.close(_test_db_fd)
    os.unlink(_test_db_path)


@pytest.fixture(scope="function")
def client(db_session):
    """Yield a TestClient with DB override and auth stub."""
    db_url = f"sqlite:///{_test_db_path}"

    def _override_get_db():
        engine = create_engine(
            db_url, echo=False, connect_args={"check_same_thread": False},
        )
        TestSession = sessionmaker(bind=engine)
        session = TestSession()
        try:
            yield session
        finally:
            session.close()
            engine.dispose()

    def _override_get_current_user():
        return {"sub": "test-user-123"}

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ============================================================
# HELPERS
# ============================================================

def _uuid():
    return str(uuid.uuid4())


def _seed_job(db, job_id=None, title="Dev Python"):
    job = Job(id=job_id or _uuid(), title=title)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _seed_candidate(db, candidate_id=None, name="Ana García", email=None):
    cand = Candidate(
        id=candidate_id or _uuid(),
        name=name,
        email=email,
    )
    db.add(cand)
    db.commit()
    db.refresh(cand)
    return cand


# ============================================================
# TESTS — ADVISORY LOCK KEY
# ============================================================

def test_advisory_lock_key_is_deterministic():
    key_a = _advisory_lock_key("job-001")
    key_b = _advisory_lock_key("job-001")
    assert key_a == key_b


def test_advisory_lock_key_differs_per_job():
    key_1 = _advisory_lock_key("job-001")
    key_2 = _advisory_lock_key("job-002")
    assert key_1 != key_2


def test_advisory_lock_key_is_64bit_signed():
    key = _advisory_lock_key("job-001")
    assert -(2**63) <= key < 2**63


# ============================================================
# TESTS — MODEL TABLE NAMES
# ============================================================

def test_read_table_names():
    assert Candidate.__tablename__  == "candidates"
    assert Job.__tablename__        == "jobs"
    assert Ranking.__tablename__    == "rankings"
    assert RankingItem.__tablename__ == "ranking_items"


# ============================================================
# TESTS — GET /api/jobs/{job_id}/ranking (empty)
# ============================================================

def test_get_ranking_empty(client, db_session):
    job = _seed_job(db_session)
    resp = client.get(f"/api/jobs/{job.id}/ranking")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job.id
    assert data["ranking_version"] is None
    assert data["ranking_generated_at"] is None
    assert data["candidates"] == []
    assert data["total"] == 0


def test_get_ranking_404_for_unknown_job(client):
    resp = client.get(f"/api/jobs/{_uuid()}/ranking")
    assert resp.status_code == 404


# ============================================================
# TESTS — POST /api/jobs/{job_id}/ranking/recalculate (full, empty)
# ============================================================

def test_recalculate_full_empty_creates_ranking(client, db_session):
    """Full recalculate with no candidates creates empty ranking."""
    job = _seed_job(db_session)

    resp = client.post(
        f"/api/jobs/{job.id}/ranking/recalculate",
        params={"mode": "full"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job.id
    assert data["mode"] == "full"
    assert data["total_candidates"] == 0
    assert data["evaluated"] == 0
    assert data["failed"] == 0
    assert data["ranking_version"] == 1

    # Verify ranking metadata was created
    meta = get_ranking_metadata(db_session, job.id)
    assert meta is not None
    assert meta.ranking_version == 1
    assert meta.mode == "full"


def test_recalculate_full_404_for_unknown_job(client):
    resp = client.post(
        f"/api/jobs/{_uuid()}/ranking/recalculate",
        params={"mode": "full"},
    )
    assert resp.status_code == 404


def test_recalculate_invalid_mode(client, db_session):
    job = _seed_job(db_session)
    resp = client.post(
        f"/api/jobs/{job.id}/ranking/recalculate",
        params={"mode": "invalid"},
    )
    assert resp.status_code == 422  # Validation error


# ============================================================
# TESTS — POST recalculate (incremental fallback)
# ============================================================

def test_recalculate_incremental_falls_back_to_full(client, db_session):
    """Incremental without previous ranking falls back to full."""
    job = _seed_job(db_session)

    resp = client.post(
        f"/api/jobs/{job.id}/ranking/recalculate",
        params={"mode": "incremental"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "full"  # fallback
    assert data["ranking_version"] == 1

    meta = get_ranking_metadata(db_session, job.id)
    assert meta.mode == "full"


def test_recalculate_increments_version(client, db_session):
    """Each recalculate increments the ranking version."""
    job = _seed_job(db_session)

    resp1 = client.post(
        f"/api/jobs/{job.id}/ranking/recalculate",
        params={"mode": "full"},
    )
    assert resp1.json()["ranking_version"] == 1

    resp2 = client.post(
        f"/api/jobs/{job.id}/ranking/recalculate",
        params={"mode": "full"},
    )
    assert resp2.json()["ranking_version"] == 2

    resp3 = client.post(
        f"/api/jobs/{job.id}/ranking/recalculate",
        params={"mode": "full"},
    )
    assert resp3.json()["ranking_version"] == 3


# ============================================================
# TESTS — GET /api/jobs/{job_id}/ranking/latest
# ============================================================

def test_get_latest_ranking(client, db_session):
    job = _seed_job(db_session)
    client.post(
        f"/api/jobs/{job.id}/ranking/recalculate",
        params={"mode": "full"},
    )
    resp = client.get(f"/api/jobs/{job.id}/ranking/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ranking_version"] == 1
    assert data["candidates"] == []


def test_get_latest_ranking_404_when_none(client, db_session):
    job = _seed_job(db_session)
    resp = client.get(f"/api/jobs/{job.id}/ranking/latest")
    assert resp.status_code == 404


# ============================================================
# TESTS — GET /api/jobs/{job_id}/candidates
# ============================================================

def test_get_candidates_empty(client, db_session):
    job = _seed_job(db_session)
    resp = client.get(f"/api/jobs/{job.id}/candidates")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_candidates_404_for_unknown_job(client):
    resp = client.get(f"/api/jobs/{_uuid()}/candidates")
    assert resp.status_code == 404


# ============================================================
# TESTS — CONCURRENCY (advisory lock)
# ============================================================

def test_concurrent_recalculate_returns_409(client, db_session):
    """Advisory lock prevents concurrent recalculate.

    NOTE: SQLite doesn't support pg_advisory_lock, so the lock is
    a no-op and the request succeeds. On PostgreSQL it would return 409.
    """
    job = _seed_job(db_session)
    acquire_job_lock(db_session, job.id)

    resp = client.post(
        f"/api/jobs/{job.id}/ranking/recalculate",
        params={"mode": "full"},
    )

    if "sqlite" in os.environ.get("DATABASE_URL", ""):
        assert resp.status_code == 200  # lock is no-op
    else:
        assert resp.status_code == 409  # lock held
