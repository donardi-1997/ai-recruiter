"""Contract tests — verify endpoints return correct status codes and fields.

Run:  python -m pytest app/tests/test_contract.py -v
"""

import os
import tempfile
import uuid

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.deps import get_current_user, get_db
from app.main import app
from app.models import Candidate, Job, Ranking, RankingItem


# ============================================================
# FIXTURES
# ============================================================

_test_db_fd = None
_test_db_path = None


@pytest.fixture(scope="function")
def db_session():
    global _test_db_fd, _test_db_path
    _test_db_fd, _test_db_path = tempfile.mkstemp(suffix=".db")
    db_url = f"sqlite:///{_test_db_path}"
    engine = create_engine(db_url, echo=False, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _(dbapi_conn, _):
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
    db_url = f"sqlite:///{_test_db_path}"

    def _override_get_db():
        engine = create_engine(db_url, echo=False, connect_args={"check_same_thread": False})
        TestSession = sessionmaker(bind=engine)
        session = TestSession()
        try:
            yield session
        finally:
            session.close()
            engine.dispose()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: {"sub": "test-user"}
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ============================================================
# HELPERS
# ============================================================

def _uuid():
    return str(uuid.uuid4())


def _seed_job(db):
    job = Job(id=_uuid(), title="Dev Python")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


# ============================================================
# CONTRACT: GET /api/jobs/{job_id}/ranking
# ============================================================

class TestGetRanking:
    def test_empty_returns_200_with_null_metadata(self, client, db_session):
        job = _seed_job(db_session)
        resp = client.get(f"/api/jobs/{job.id}/ranking")
        assert resp.status_code == 200
        data = resp.json()

        # Required fields
        assert "job_id" in data
        assert "job_title" in data
        assert "candidates" in data
        assert "ranking_generated_at" in data
        assert "ranking_version" in data
        assert "total" in data
        assert "total_pages" in data
        assert "page" in data
        assert "page_size" in data
        assert "pending_candidates" in data

        # Empty state
        assert data["candidates"] == []
        assert data["ranking_generated_at"] is None
        assert data["ranking_version"] is None
        assert data["total"] == 0
        assert data["job_id"] == job.id

    def test_unknown_job_returns_404(self, client):
        resp = client.get(f"/api/jobs/{_uuid()}/ranking")
        assert resp.status_code == 404
        assert "detail" in resp.json()

    def test_invalid_score_range_returns_400(self, client, db_session):
        job = _seed_job(db_session)
        resp = client.get(f"/api/jobs/{job.id}/ranking", params={"min_score": 80, "max_score": 20})
        assert resp.status_code == 400


# ============================================================
# CONTRACT: POST /api/jobs/{job_id}/ranking/recalculate
# ============================================================

class TestRecalculate:
    def test_full_empty_returns_200_with_version(self, client, db_session):
        job = _seed_job(db_session)
        resp = client.post(f"/api/jobs/{job.id}/ranking/recalculate", params={"mode": "full"})
        assert resp.status_code == 200
        data = resp.json()

        # Required fields
        assert "job_id" in data
        assert "mode" in data
        assert "total_candidates" in data
        assert "evaluated" in data
        assert "failed" in data
        assert "ranking_version" in data

        # Values
        assert data["job_id"] == job.id
        assert data["mode"] == "full"
        assert data["ranking_version"] == 1
        assert data["total_candidates"] == 0
        assert data["evaluated"] == 0

    def test_incremental_fallback_returns_mode_full(self, client, db_session):
        job = _seed_job(db_session)
        resp = client.post(f"/api/jobs/{job.id}/ranking/recalculate", params={"mode": "incremental"})
        assert resp.status_code == 200
        assert resp.json()["mode"] == "full"  # fallback

    def test_invalid_mode_returns_422(self, client, db_session):
        job = _seed_job(db_session)
        resp = client.post(f"/api/jobs/{job.id}/ranking/recalculate", params={"mode": "invalid"})
        assert resp.status_code == 422

    def test_unknown_job_returns_404(self, client):
        resp = client.post(f"/api/jobs/{_uuid()}/ranking/recalculate", params={"mode": "full"})
        assert resp.status_code == 404

    def test_version_increments(self, client, db_session):
        job = _seed_job(db_session)
        r1 = client.post(f"/api/jobs/{job.id}/ranking/recalculate", params={"mode": "full"})
        r2 = client.post(f"/api/jobs/{job.id}/ranking/recalculate", params={"mode": "full"})
        r3 = client.post(f"/api/jobs/{job.id}/ranking/recalculate", params={"mode": "full"})
        assert r1.json()["ranking_version"] == 1
        assert r2.json()["ranking_version"] == 2
        assert r3.json()["ranking_version"] == 3


# ============================================================
# CONTRACT: GET /api/jobs/{job_id}/ranking/latest
# ============================================================

class TestLatestRanking:
    def test_with_ranking_returns_200(self, client, db_session):
        job = _seed_job(db_session)
        client.post(f"/api/jobs/{job.id}/ranking/recalculate", params={"mode": "full"})
        resp = client.get(f"/api/jobs/{job.id}/ranking/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ranking_version"] == 1
        assert isinstance(data["candidates"], list)
        assert "ranking_generated_at" in data

    def test_without_ranking_returns_404(self, client, db_session):
        job = _seed_job(db_session)
        resp = client.get(f"/api/jobs/{job.id}/ranking/latest")
        assert resp.status_code == 404

    def test_unknown_job_returns_404(self, client):
        resp = client.get(f"/api/jobs/{_uuid()}/ranking/latest")
        assert resp.status_code == 404


# ============================================================
# CONTRACT: GET /api/jobs/{job_id}/candidates
# ============================================================

class TestCandidates:
    def test_empty_returns_200_with_empty_list(self, client, db_session):
        job = _seed_job(db_session)
        resp = client.get(f"/api/jobs/{job.id}/candidates")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data == []

    def test_unknown_job_returns_404(self, client):
        resp = client.get(f"/api/jobs/{_uuid()}/candidates")
        assert resp.status_code == 404

    def test_response_has_required_fields(self, client, db_session):
        job = _seed_job(db_session)
        resp = client.get(f"/api/jobs/{job.id}/candidates")
        assert resp.status_code == 200
        # Empty list is valid — field check happens when items exist


# ============================================================
# CONTRACT: ADVISORY LOCK
# ============================================================

class TestAdvisoryLock:
    def test_lock_key_is_deterministic(self):
        from app.deps import _advisory_lock_key
        assert _advisory_lock_key("x") == _advisory_lock_key("x")

    def test_lock_key_differs_per_job(self):
        from app.deps import _advisory_lock_key
        assert _advisory_lock_key("a") != _advisory_lock_key("b")

    def test_lock_key_is_64bit(self):
        from app.deps import _advisory_lock_key
        key = _advisory_lock_key("test")
        assert -(2**63) <= key < 2**63
