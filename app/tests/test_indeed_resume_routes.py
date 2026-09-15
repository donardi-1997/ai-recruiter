"""HTTP contracts for Indeed resume processing state and canonical CV access."""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.deps import get_current_user, get_db
from app.domains.indeed.resume_models import IndeedResumeIngestion
from app.infrastructure.imports import storage
from app.main import app
from app.models import Candidate, IndeedCandidateLink, Job, JobCandidate


@pytest.fixture()
def db_session():
    fd, path = tempfile.mkstemp(suffix=".db")
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
        os.close(fd)
        os.unlink(path)


@pytest.fixture()
def api(db_session):
    principal = {"sub": "owner-1", "email": "hr@asiati.com"}

    def override_db():
        Session = sessionmaker(bind=db_session.get_bind())
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: dict(principal)
    with TestClient(app) as client:
        yield client, principal
    app.dependency_overrides.clear()


def _seed(db, *, owner_sub="owner-1", status="COMPLETED"):
    candidate = Candidate(name="Ana Perez", email="ana@example.com", owner_sub=owner_sub)
    job = Job(title="Country Manager", description="Lead the market", owner_sub=owner_sub)
    db.add_all([candidate, job])
    db.flush()
    db.add(JobCandidate(job_id=job.id, candidate_id=candidate.id))
    link = IndeedCandidateLink(
        owner_sub=owner_sub,
        candidate_id=candidate.id,
        job_id=job.id,
        asset_id=f"asset-{owner_sub}",
        source_name="Indeed",
        resume_name="ana.pdf",
        resume_url="https://resume.invalid/ana.pdf?X-Amz-Signature=do-not-leak",
    )
    db.add(link)
    db.flush()
    task = IndeedResumeIngestion(
        owner_sub=owner_sub,
        candidate_link_id=link.id,
        status=status,
        resume_sha256="a" * 64 if status == "COMPLETED" else None,
        canonical_s3_key=(f"documents/cv-{candidate.id}.pdf" if status == "COMPLETED" else None),
    )
    db.add(task)
    db.commit()
    return job, candidate, link, task


def test_indeed_candidate_detail_exposes_durable_resume_state_not_provider_url(api, db_session):
    client, _principal = api
    job, candidate, _link, _task = _seed(db_session)

    response = client.get(
        f"/api/jobs/{job.id}/candidates/{candidate.id}/integrations/indeed"
    )

    assert response.status_code == 200
    payload = response.json()
    assert "resume_url" not in payload
    assert "do-not-leak" not in response.text
    assert payload["resume"] == {
        "name": "ana.pdf",
        "status": "COMPLETED",
        "available": True,
        "sha256": "a" * 64,
        "last_error_code": None,
    }


def test_canonical_resume_route_returns_short_lived_url(api, db_session, monkeypatch):
    client, _principal = api
    job, candidate, _link, _task = _seed(db_session)
    monkeypatch.setattr(
        storage,
        "create_canonical_candidate_download",
        lambda candidate_id, expires_in=300: {
            "url": "https://canonical.invalid/download",
            "expires_in": 300,
            "key": f"documents/cv-{candidate_id}.pdf",
        },
    )

    response = client.get(f"/api/jobs/{job.id}/candidates/{candidate.id}/resume")

    assert response.status_code == 200
    assert response.json() == {
        "url": "https://canonical.invalid/download",
        "expires_in": 300,
    }


def test_canonical_resume_route_is_owner_scoped(api, db_session, monkeypatch):
    client, _principal = api
    job, candidate, _link, _task = _seed(db_session, owner_sub="owner-2")
    monkeypatch.setattr(
        storage,
        "create_canonical_candidate_download",
        lambda *_a, **_k: pytest.fail("must not issue cross-tenant URL"),
    )

    response = client.get(f"/api/jobs/{job.id}/candidates/{candidate.id}/resume")

    assert response.status_code == 404


def test_canonical_resume_route_returns_404_when_canonical_document_missing(api, db_session, monkeypatch):
    client, _principal = api
    job, candidate, _link, _task = _seed(db_session, status="INGESTING")
    monkeypatch.setattr(storage, "create_canonical_candidate_download", lambda *_a, **_k: None)

    response = client.get(f"/api/jobs/{job.id}/candidates/{candidate.id}/resume")

    assert response.status_code == 404
