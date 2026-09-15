"""Security and ranking integrity regressions."""

import os
import tempfile
import uuid

os.environ["DATABASE_URL"] = (
    "sqlite:///:memory:"
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import crud
from app.db import Base
from app.deps import (
    get_current_user,
    get_db,
)
from app.evaluation import (
    recommendation_for_score,
)
from app.main import app
from app.models import (
    Candidate,
    Job,
)


@pytest.fixture()
def db_bundle():
    fd, db_path = tempfile.mkstemp(
        suffix=".db"
    )

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={
            "check_same_thread": False
        },
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute(
            "PRAGMA foreign_keys=ON"
        )
        cursor.close()

    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    yield session, engine, db_path

    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()

    os.close(fd)
    os.unlink(db_path)


@pytest.fixture()
def client(db_bundle):
    session, engine, db_path = db_bundle

    def override_db():
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[
        get_db
    ] = override_db

    app.dependency_overrides[
        get_current_user
    ] = lambda: {
        "sub": "user-a",
        "email": "a@example.com",
    }

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def uid():
    return str(uuid.uuid4())


def seed_owned_data(db):
    job_a = Job(
        id=uid(),
        title="Job A",
        description="Python APIs REST",
        owner_sub="user-a",
    )

    job_b = Job(
        id=uid(),
        title="Job B",
        description="AWS",
        owner_sub="user-b",
    )

    candidate_a = Candidate(
        id=uid(),
        name="Candidate A",
        owner_sub="user-a",
    )

    candidate_b = Candidate(
        id=uid(),
        name="Candidate B",
        owner_sub="user-b",
    )

    db.add_all([
        job_a,
        job_b,
        candidate_a,
        candidate_b,
    ])
    db.commit()

    return (
        job_a,
        job_b,
        candidate_a,
        candidate_b,
    )


def test_score_bands_have_all_four_labels():
    assert (
        recommendation_for_score(100)
        == "STRONG_MATCH"
    )
    assert (
        recommendation_for_score(80)
        == "STRONG_MATCH"
    )
    assert (
        recommendation_for_score(79)
        == "GOOD_MATCH"
    )
    assert (
        recommendation_for_score(60)
        == "GOOD_MATCH"
    )
    assert (
        recommendation_for_score(59)
        == "PARTIAL_MATCH"
    )
    assert (
        recommendation_for_score(40)
        == "PARTIAL_MATCH"
    )
    assert (
        recommendation_for_score(39)
        == "LOW_MATCH"
    )


def test_lists_are_isolated_by_owner(
    client,
    db_bundle,
):
    db, _, _ = db_bundle

    (
        job_a,
        job_b,
        candidate_a,
        candidate_b,
    ) = seed_owned_data(db)

    jobs = client.get("/api/jobs")
    assert jobs.status_code == 200

    job_ids = {
        item["job_id"]
        for item in jobs.json()
    }

    assert job_a.id in job_ids
    assert job_b.id not in job_ids

    candidates = client.get(
        "/api/candidates"
    )
    assert candidates.status_code == 200

    candidate_ids = {
        item["candidate_id"]
        for item in candidates.json()
    }

    assert candidate_a.id in candidate_ids
    assert candidate_b.id not in candidate_ids

    hidden = client.get(
        f"/api/candidates/{candidate_b.id}"
    )

    assert hidden.status_code == 404


def test_scope_all_only_uses_current_owner(
    client,
    db_bundle,
    monkeypatch,
):
    import app.evaluation as evaluation

    db, _, _ = db_bundle

    (
        job_a,
        _,
        candidate_a,
        candidate_b,
    ) = seed_owned_data(db)

    monkeypatch.setattr(
        evaluation,
        "retrieve_candidate",
        lambda **kwargs: [{
            "content": {
                "text":
                    "Python APIs REST experience"
            }
        }],
    )

    monkeypatch.setattr(
        evaluation,
        "evaluate_candidate",
        lambda **kwargs: {
            "status": "COMPLETED",
            "match_score": 70,
            "recommendation": "GOOD_MATCH",
            "summary": (
                "El candidato demuestra experiencia "
                "relevante en Python y APIs REST. "
                "Existe evidencia suficiente para "
                "considerarlo un buen ajuste para "
                "la vacante y continuar con una "
                "entrevista técnica detallada."
            ),
            "strengths": ["Python"],
            "gaps": ["AWS"],
            "requirements": [{
                "requirement": "Python",
                "status": "MATCH",
                "evidence":
                    "Experiencia profesional con Python",
            }],
        },
    )

    response = client.post(
        f"/api/jobs/{job_a.id}/ranking/recalculate",
        params={
            "mode": "incremental",
            "scope": "all",
        },
    )

    assert response.status_code == 200

    data = response.json()

    # User A owns exactly one candidate.
    assert data["total_candidates"] == 1

    ranking = client.get(
        f"/api/jobs/{job_a.id}/ranking",
        params={
            "scope": "all",
            "page": 1,
            "page_size": 10,
        },
    )

    assert ranking.status_code == 200

    ids = {
        item["candidate_id"]
        for item in ranking.json()[
            "candidates"
        ]
    }

    assert candidate_a.id in ids
    assert candidate_b.id not in ids


def test_structured_requirements_survive_round_trip(
    client,
    db_bundle,
    monkeypatch,
):
    import app.evaluation as evaluation

    db, _, _ = db_bundle

    (
        job_a,
        _,
        candidate_a,
        _,
    ) = seed_owned_data(db)

    expected_requirements = [
        {
            "requirement": "Python",
            "status": "MATCH",
            "evidence":
                "Desarrolló servicios con Python.",
        },
        {
            "requirement": "AWS",
            "status": "PARTIAL",
            "evidence":
                "Trabajó con S3, sin evidencia "
                "de arquitectura avanzada.",
        },
        {
            "requirement": "Kubernetes",
            "status": "MISSING",
            "evidence": None,
        },
    ]

    monkeypatch.setattr(
        evaluation,
        "retrieve_candidate",
        lambda **kwargs: [{
            "content": {
                "text":
                    "Python S3 backend experience"
            }
        }],
    )

    monkeypatch.setattr(
        evaluation,
        "evaluate_candidate",
        lambda **kwargs: {
            "status": "COMPLETED",
            "match_score": 58,
            "recommendation":
                "PARTIAL_MATCH",
            "summary": (
                "El candidato cumple parte de los "
                "requisitos técnicos de la vacante. "
                "Cuenta con experiencia concreta "
                "en Python y exposición parcial a "
                "AWS, pero no presenta evidencia "
                "suficiente en Kubernetes."
            ),
            "strengths": ["Python"],
            "gaps": ["AWS", "Kubernetes"],
            "requirements":
                expected_requirements,
        },
    )

    evaluated = client.post(
        f"/api/candidates/{candidate_a.id}/evaluate-job",
        json={
            "job_id": job_a.id
        },
    )

    assert evaluated.status_code == 200

    assert (
        evaluated.json()["requirements"]
        == expected_requirements
    )

    requirements = client.get(
        f"/api/jobs/{job_a.id}/candidates/"
        f"{candidate_a.id}/requirements"
    )

    assert requirements.status_code == 200

    assert (
        requirements.json()["requirements"]
        == expected_requirements
    )

    partial = (
        requirements.json()[
            "requirements"
        ][1]
    )

    assert partial["status"] == "PARTIAL"
    assert partial["evidence"] is not None
