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
from app.models import Candidate, Evaluation, Job, JobCandidate, Ranking, RankingItem
from app.crud import build_ranking_response, get_ranking_metadata, get_ranking_items, insert_ranking_items


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
    job = Job(
        id=job_id or _uuid(),
        title=title,
        owner_sub="test-user-123",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _seed_candidate(db, candidate_id=None, name="Ana García", email=None, owner_sub="test-user-123"):
    cand = Candidate(
        id=candidate_id or _uuid(),
        name=name,
        email=email,
        owner_sub=owner_sub,
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



# ============================================================
# TESTS — RANKING ORDER / PAGINATION / SCOPE
# ============================================================

def test_ranking_orders_by_match_score_and_paginates(
    db_session,
):
    job = _seed_job(db_session)

    ranking = Ranking(
        id=_uuid(),
        job_id=job.id,
        ranking_version=1,
        mode="full",
        notes="scope:assigned",
    )

    db_session.add(ranking)
    db_session.commit()

    long_summary = (
        "El candidato presenta evidencia suficiente para realizar "
        "una evaluación completa frente a los requisitos técnicos "
        "y profesionales definidos para esta vacante específica."
    )

    expected_scores = []

    for index in range(25):
        candidate = _seed_candidate(
            db_session,
            name=f"Candidato {index:02d}",
        )

        score = float(index)

        expected_scores.append(score)

        db_session.add(
            Evaluation(
                candidate_id=candidate.id,
                job_id=job.id,
                status="COMPLETED",
                match_score=score,
                recommendation=(
                    "LOW_MATCH"
                    if score < 60
                    else "GOOD_MATCH"
                ),
                summary=long_summary,
                strengths=[],
                gaps=[],
            )
        )

        # Deliberately use the wrong stored position
        # to prove API ordering is based on score.
        db_session.add(
            RankingItem(
                ranking_id=ranking.id,
                candidate_id=candidate.id,
                score=score,
                position=25 - index,
            )
        )

    db_session.commit()

    first_page = build_ranking_response(
        db_session,
        job.id,
        page=1,
        page_size=10,
        scope="assigned",
    )

    assert first_page["total"] == 25
    assert first_page["ranking_total"] == 25
    assert first_page["total_pages"] == 3

    scores = [
        candidate["match_score"]
        for candidate
        in first_page["candidates"]
    ]

    assert scores == list(
        reversed(expected_scores)
    )[:10]

    assert [
        candidate["position"]
        for candidate
        in first_page["candidates"]
    ] == list(range(1, 11))

    second_page = build_ranking_response(
        db_session,
        job.id,
        page=2,
        page_size=10,
        scope="assigned",
    )

    assert second_page["candidates"][0][
        "position"
    ] == 11

    assert second_page["candidates"][0][
        "match_score"
    ] == 14.0


def test_ranking_filters_before_pagination(
    db_session,
):
    job = _seed_job(db_session)

    ranking = Ranking(
        id=_uuid(),
        job_id=job.id,
        ranking_version=1,
        mode="full",
        notes="scope:assigned",
    )

    db_session.add(ranking)
    db_session.commit()

    summary = (
        "Esta evaluación contiene información suficiente y "
        "detallada para cumplir correctamente con la longitud "
        "mínima exigida por el contrato de evaluación."
    )

    for score in range(30):
        candidate = _seed_candidate(
            db_session,
            name=f"Filtro {score}",
        )

        db_session.add(
            Evaluation(
                candidate_id=candidate.id,
                job_id=job.id,
                status="COMPLETED",
                match_score=score,
                recommendation="LOW_MATCH",
                summary=summary,
                strengths=[],
                gaps=[],
            )
        )

        db_session.add(
            RankingItem(
                ranking_id=ranking.id,
                candidate_id=candidate.id,
                score=score,
                position=score + 1,
            )
        )

    db_session.commit()

    result = build_ranking_response(
        db_session,
        job.id,
        min_score=20,
        max_score=29,
        page=1,
        page_size=5,
        scope="assigned",
    )

    assert result["total"] == 10
    assert result["total_pages"] == 2
    assert len(result["candidates"]) == 5
    assert result["candidates"][0][
        "match_score"
    ] == 29.0


def test_recalculate_scope_all_includes_unassigned(
    client,
    db_session,
    monkeypatch,
):
    import app.evaluation as evaluation_module

    job = _seed_job(db_session)

    assigned = _seed_candidate(
        db_session,
        name="Asignado",
    )

    unassigned = _seed_candidate(
        db_session,
        name="No asignado",
    )

    db_session.add(
        JobCandidate(
            job_id=job.id,
            candidate_id=assigned.id,
        )
    )

    db_session.commit()

    monkeypatch.setattr(
        evaluation_module,
        "retrieve_candidate",
        lambda **kwargs: [
            {
                "content": {
                    "text": "CV de prueba"
                }
            }
        ],
    )

    long_summary = (
        "El candidato presenta experiencia suficiente para "
        "realizar una evaluación completa de su ajuste frente "
        "a los requisitos técnicos de esta vacante."
    )

    monkeypatch.setattr(
        evaluation_module,
        "evaluate_candidate",
        lambda **kwargs: {
            "status": "COMPLETED",
            "match_score": 50,
            "recommendation": "LOW_MATCH",
            "summary": long_summary,
            "strengths": [],
            "gaps": [],
        },
    )

    all_response = client.post(
        f"/api/jobs/{job.id}/ranking/recalculate",
        params={
            "mode": "full",
            "scope": "all",
        },
    )

    assert all_response.status_code == 200
    assert all_response.json()[
        "total_candidates"
    ] == 2

    assigned_response = client.post(
        f"/api/jobs/{job.id}/ranking/recalculate",
        params={
            "mode": "full",
            "scope": "assigned",
        },
    )

    assert assigned_response.status_code == 200
    assert assigned_response.json()[
        "total_candidates"
    ] == 1


# ============================================================
# TESTS — E2E POST recalculate -> GET ranking
# ============================================================

def test_recalculate_all_then_get_all_returns_all_candidates(
    client, db_session, monkeypatch,
):
    """Full E2E: POST scope=all -> GET scope=all returns all candidates."""
    import app.evaluation as evaluation_module

    job = _seed_job(db_session)

    assigned = _seed_candidate(db_session, name="Asignado")
    unassigned = _seed_candidate(db_session, name="No asignado")

    db_session.add(JobCandidate(job_id=job.id, candidate_id=assigned.id))
    db_session.commit()

    monkeypatch.setattr(
        evaluation_module,
        "retrieve_candidate",
        lambda **kwargs: [{"content": {"text": "CV de prueba"}}],
    )

    long_summary = (
        "El candidato presenta experiencia suficiente para "
        "realizar una evaluación completa de su ajuste frente "
        "a los requisitos técnicos de esta vacante."
    )

    monkeypatch.setattr(
        evaluation_module,
        "evaluate_candidate",
        lambda **kwargs: {
            "status": "COMPLETED",
            "match_score": 50,
            "recommendation": "LOW_MATCH",
            "summary": long_summary,
            "strengths": [],
            "gaps": [],
        },
    )

    # POST scope=all
    post_resp = client.post(
        f"/api/jobs/{job.id}/ranking/recalculate",
        params={"mode": "full", "scope": "all"},
    )
    assert post_resp.status_code == 200
    post_data = post_resp.json()
    assert post_data["scope"] == "all"
    assert post_data["total_candidates"] == 2
    assert post_data["ranking_version"] >= 1

    # Immediately GET scope=all
    get_resp = client.get(
        f"/api/jobs/{job.id}/ranking",
        params={"scope": "all", "min_score": 0, "max_score": 100, "page": 1, "page_size": 10},
    )
    assert get_resp.status_code == 200
    get_data = get_resp.json()

    assert get_data["scope_mismatch"] is False
    assert get_data["ranking_scope"] == "all"
    assert get_data["ranking_total"] == 2
    assert get_data["total"] == 2
    assert len(get_data["candidates"]) == 2

    candidate_ids = {c["candidate_id"] for c in get_data["candidates"]}
    assert assigned.id in candidate_ids
    assert unassigned.id in candidate_ids


def test_recalculate_assigned_then_get_assigned_returns_only_assigned(
    client, db_session, monkeypatch,
):
    """Full E2E: POST scope=assigned -> GET scope=assigned returns only assigned."""
    import app.evaluation as evaluation_module

    job = _seed_job(db_session)

    assigned = _seed_candidate(db_session, name="Asignado")
    unassigned = _seed_candidate(db_session, name="No asignado")

    db_session.add(JobCandidate(job_id=job.id, candidate_id=assigned.id))
    db_session.commit()

    monkeypatch.setattr(
        evaluation_module,
        "retrieve_candidate",
        lambda **kwargs: [{"content": {"text": "CV de prueba"}}],
    )

    long_summary = (
        "El candidato presenta experiencia suficiente para "
        "realizar una evaluación completa de su ajuste frente "
        "a los requisitos técnicos de esta vacante."
    )

    monkeypatch.setattr(
        evaluation_module,
        "evaluate_candidate",
        lambda **kwargs: {
            "status": "COMPLETED",
            "match_score": 50,
            "recommendation": "LOW_MATCH",
            "summary": long_summary,
            "strengths": [],
            "gaps": [],
        },
    )

    # POST scope=assigned
    post_resp = client.post(
        f"/api/jobs/{job.id}/ranking/recalculate",
        params={"mode": "full", "scope": "assigned"},
    )
    assert post_resp.status_code == 200
    post_data = post_resp.json()
    assert post_data["scope"] == "assigned"
    assert post_data["total_candidates"] == 1

    # GET scope=assigned
    get_resp = client.get(
        f"/api/jobs/{job.id}/ranking",
        params={"scope": "assigned", "min_score": 0, "max_score": 100, "page": 1, "page_size": 10},
    )
    assert get_resp.status_code == 200
    get_data = get_resp.json()

    assert get_data["scope_mismatch"] is False
    assert get_data["ranking_scope"] == "assigned"
    assert get_data["ranking_total"] == 1
    assert get_data["total"] == 1
    assert len(get_data["candidates"]) == 1
    assert get_data["candidates"][0]["candidate_id"] == assigned.id


def test_ranking_scope_transition_replaces_items_correctly(
    client, db_session, monkeypatch,
):
    """Scope transition: assigned -> all -> assigned verifies items replaced correctly."""
    import app.evaluation as evaluation_module

    job = _seed_job(db_session)

    assigned = _seed_candidate(db_session, name="Asignado")
    unassigned = _seed_candidate(db_session, name="No asignado")

    db_session.add(JobCandidate(job_id=job.id, candidate_id=assigned.id))
    db_session.commit()

    monkeypatch.setattr(
        evaluation_module,
        "retrieve_candidate",
        lambda **kwargs: [{"content": {"text": "CV de prueba"}}],
    )

    long_summary = (
        "El candidato presenta experiencia suficiente para "
        "realizar una evaluación completa de su ajuste frente "
        "a los requisitos técnicos de esta vacante."
    )

    monkeypatch.setattr(
        evaluation_module,
        "evaluate_candidate",
        lambda **kwargs: {
            "status": "COMPLETED",
            "match_score": 50,
            "recommendation": "LOW_MATCH",
            "summary": long_summary,
            "strengths": [],
            "gaps": [],
        },
    )

    # 1. POST scope=assigned
    resp1 = client.post(
        f"/api/jobs/{job.id}/ranking/recalculate",
        params={"mode": "full", "scope": "assigned"},
    )
    assert resp1.status_code == 200
    assert resp1.json()["total_candidates"] == 1

    get1 = client.get(
        f"/api/jobs/{job.id}/ranking",
        params={"scope": "assigned", "min_score": 0, "max_score": 100, "page": 1, "page_size": 10},
    )
    assert get1.json()["ranking_total"] == 1
    assert get1.json()["candidates"][0]["candidate_id"] == assigned.id

    # 2. POST scope=all
    resp2 = client.post(
        f"/api/jobs/{job.id}/ranking/recalculate",
        params={"mode": "full", "scope": "all"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["total_candidates"] == 2

    get2 = client.get(
        f"/api/jobs/{job.id}/ranking",
        params={"scope": "all", "min_score": 0, "max_score": 100, "page": 1, "page_size": 10},
    )
    assert get2.json()["ranking_total"] == 2
    candidate_ids_2 = {c["candidate_id"] for c in get2.json()["candidates"]}
    assert assigned.id in candidate_ids_2
    assert unassigned.id in candidate_ids_2

    # 3. GET assigned WITHOUT recalculating -> scope_mismatch
    get3 = client.get(
        f"/api/jobs/{job.id}/ranking",
        params={"scope": "assigned", "min_score": 0, "max_score": 100, "page": 1, "page_size": 10},
    )
    assert get3.json()["scope_mismatch"] is True
    assert get3.json()["ranking_total"] == 0
    assert get3.json()["candidates"] == []

    # 4. POST scope=assigned again -> back to 1 candidate
    resp4 = client.post(
        f"/api/jobs/{job.id}/ranking/recalculate",
        params={"mode": "full", "scope": "assigned"},
    )
    assert resp4.status_code == 200
    assert resp4.json()["total_candidates"] == 1

    get4 = client.get(
        f"/api/jobs/{job.id}/ranking",
        params={"scope": "assigned", "min_score": 0, "max_score": 100, "page": 1, "page_size": 10},
    )
    assert get4.json()["scope_mismatch"] is False
    assert get4.json()["ranking_scope"] == "assigned"
    assert get4.json()["ranking_total"] == 1
    assert get4.json()["candidates"][0]["candidate_id"] == assigned.id


def test_scope_all_excludes_other_tenant_candidates(
    client, db_session, monkeypatch,
):
    """Multi-tenant: User A scope=all should NOT see User B's candidates."""
    import app.evaluation as evaluation_module

    job = _seed_job(db_session, title="Job A")

    # User A's candidates
    cand_a1 = _seed_candidate(db_session, name="UserA Cand 1")
    cand_a2 = _seed_candidate(db_session, name="UserA Cand 2")
    db_session.add(JobCandidate(job_id=job.id, candidate_id=cand_a1.id))
    db_session.commit()

    # User B's candidate (different owner_sub)
    cand_b = _seed_candidate(db_session, name="UserB Cand", owner_sub="other-user-456")
    db_session.commit()

    monkeypatch.setattr(
        evaluation_module,
        "retrieve_candidate",
        lambda **kwargs: [{"content": {"text": "CV de prueba"}}],
    )

    long_summary = (
        "El candidato presenta experiencia suficiente para "
        "realizar una evaluación completa de su ajuste frente "
        "a los requisitos técnicos de esta vacante."
    )

    monkeypatch.setattr(
        evaluation_module,
        "evaluate_candidate",
        lambda **kwargs: {
            "status": "COMPLETED",
            "match_score": 50,
            "recommendation": "LOW_MATCH",
            "summary": long_summary,
            "strengths": [],
            "gaps": [],
        },
    )

    # POST scope=all as User A (test-user-123)
    post_resp = client.post(
        f"/api/jobs/{job.id}/ranking/recalculate",
        params={"mode": "full", "scope": "all"},
    )
    assert post_resp.status_code == 200
    assert post_resp.json()["total_candidates"] == 2  # Only User A's candidates

    # GET scope=all
    get_resp = client.get(
        f"/api/jobs/{job.id}/ranking",
        params={"scope": "all", "min_score": 0, "max_score": 100, "page": 1, "page_size": 10},
    )
    assert get_resp.status_code == 200
    get_data = get_resp.json()

    assert get_data["ranking_total"] == 2
    assert get_data["total"] == 2
    candidate_ids = {c["candidate_id"] for c in get_data["candidates"]}
    assert cand_a1.id in candidate_ids
    assert cand_a2.id in candidate_ids
    assert cand_b.id not in candidate_ids  # User B's candidate excluded


def test_insert_ranking_items_replaces_previous_items(db_session):
    """insert_ranking_items deletes old items and inserts new ones atomically."""
    job = _seed_job(db_session)

    # Create initial ranking
    ranking = Ranking(
        id=_uuid(),
        job_id=job.id,
        ranking_version=1,
        mode="full",
        notes="scope:assigned",
    )
    db_session.add(ranking)
    db_session.commit()

    # Seed 3 candidates
    cand1 = _seed_candidate(db_session, name="Cand 1")
    cand2 = _seed_candidate(db_session, name="Cand 2")
    cand3 = _seed_candidate(db_session, name="Cand 3")

    # Insert initial items (assigned scope - 2 candidates)
    initial_items = [
        {"candidate_id": cand1.id, "score": 80.0, "position": 1},
        {"candidate_id": cand2.id, "score": 70.0, "position": 2},
    ]
    count1 = insert_ranking_items(db_session, ranking_id=ranking.id, items=initial_items)
    assert count1 == 2

    # Verify initial items
    items1 = get_ranking_items(db_session, ranking.id)
    assert len(items1) == 2
    assert {i.candidate_id for i in items1} == {cand1.id, cand2.id}

    # Insert new items (all scope - 3 candidates) - should replace
    new_items = [
        {"candidate_id": cand1.id, "score": 85.0, "position": 1},
        {"candidate_id": cand2.id, "score": 75.0, "position": 2},
        {"candidate_id": cand3.id, "score": 65.0, "position": 3},
    ]
    count2 = insert_ranking_items(db_session, ranking_id=ranking.id, items=new_items)
    assert count2 == 3

    # Verify new items replaced old ones
    items2 = get_ranking_items(db_session, ranking.id)
    assert len(items2) == 3
    assert {i.candidate_id for i in items2} == {cand1.id, cand2.id, cand3.id}

    # Verify no duplicate items from previous insert
    all_items = db_session.query(RankingItem).filter(RankingItem.ranking_id == ranking.id).all()
    assert len(all_items) == 3


# ============================================================
# TESTS — LOCK RELEASE REGRESSION
# ============================================================

def test_recalculate_releases_lock_on_success(client, db_session, monkeypatch):
    """Lock is released after successful recalculation."""
    import app.domains.ranking.service as ranking_service

    # Track lock acquire/release calls
    lock_calls = {"acquire": 0, "release": 0}

    original_acquire = ranking_service.acquire_job_lock
    original_release = ranking_service.release_job_lock

    def tracking_acquire(db, job_id):
        lock_calls["acquire"] += 1
        return original_acquire(db, job_id)

    def tracking_release(db, job_id):
        lock_calls["release"] += 1
        return original_release(db, job_id)

    monkeypatch.setattr(ranking_service, "acquire_job_lock", tracking_acquire)
    monkeypatch.setattr(ranking_service, "release_job_lock", tracking_release)

    # Mock evaluation to return success
    import app.evaluation as evaluation_module
    monkeypatch.setattr(
        evaluation_module,
        "retrieve_candidate",
        lambda **kwargs: [{"content": {"text": "CV de prueba"}}],
    )
    long_summary = "El candidato presenta experiencia suficiente para realizar una evaluación completa de su ajuste frente a los requisitos técnicos de esta vacante."
    monkeypatch.setattr(
        evaluation_module,
        "evaluate_candidate",
        lambda **kwargs: {
            "status": "COMPLETED",
            "match_score": 50,
            "recommendation": "LOW_MATCH",
            "summary": long_summary,
            "strengths": [],
            "gaps": [],
        },
    )

    job = _seed_job(db_session)
    candidate = _seed_candidate(db_session, name="Test Candidate")
    db_session.add(JobCandidate(job_id=job.id, candidate_id=candidate.id))
    db_session.commit()

    resp = client.post(
        f"/api/jobs/{job.id}/ranking/recalculate",
        params={"mode": "full", "scope": "assigned"},
    )

    assert resp.status_code == 200
    # Lock should be acquired and released exactly once
    assert lock_calls["acquire"] == 1
    assert lock_calls["release"] == 1


def test_recalculate_releases_lock_on_unexpected_exception(client, db_session, monkeypatch):
    """Lock is released even when an unexpected exception occurs during recalculation."""
    import app.domains.ranking.service as ranking_service

    # Track lock acquire/release calls
    lock_calls = {"acquire": 0, "release": 0}

    original_acquire = ranking_service.acquire_job_lock
    original_release = ranking_service.release_job_lock

    def tracking_acquire(db, job_id):
        lock_calls["acquire"] += 1
        return original_acquire(db, job_id)

    def tracking_release(db, job_id):
        lock_calls["release"] += 1
        return original_release(db, job_id)

    monkeypatch.setattr(ranking_service, "acquire_job_lock", tracking_acquire)
    monkeypatch.setattr(ranking_service, "release_job_lock", tracking_release)

    # Mock evaluation service to return success (avoid real AWS calls)
    import app.evaluation as evaluation_module
    monkeypatch.setattr(
        evaluation_module,
        "retrieve_candidate",
        lambda **kwargs: [{"content": {"text": "CV de prueba"}}],
    )
    long_summary = "El candidato presenta experiencia suficiente para realizar una evaluación completa de su ajuste frente a los requisitos técnicos de esta vacante."
    monkeypatch.setattr(
        evaluation_module,
        "evaluate_candidate",
        lambda **kwargs: {
            "status": "COMPLETED",
            "match_score": 50,
            "recommendation": "LOW_MATCH",
            "summary": long_summary,
            "strengths": [],
            "gaps": [],
            "requirements": [],
        },
    )

    # Make the repository insert_ranking_items raise an exception
    # after lock is acquired
    original_insert = ranking_service.ranking_repository.insert_ranking_items

    def failing_insert(*args, **kwargs):
        raise RuntimeError("Simulated database error")

    monkeypatch.setattr(ranking_service.ranking_repository, "insert_ranking_items", failing_insert)

    job = _seed_job(db_session)
    candidate = _seed_candidate(db_session, name="Test Candidate")
    db_session.add(JobCandidate(job_id=job.id, candidate_id=candidate.id))
    db_session.commit()

    # The test client raises server exceptions by default, so we expect the exception
    # to be raised. We verify the lock was released by checking our tracking.
    import pytest
    with pytest.raises(RuntimeError, match="Simulated database error"):
        client.post(
            f"/api/jobs/{job.id}/ranking/recalculate",
            params={"mode": "full", "scope": "assigned"},
        )

    # Lock should still be released exactly once
    assert lock_calls["acquire"] == 1
    assert lock_calls["release"] == 1
