"""Contract tests for paginated and sortable job listing."""

import os
import tempfile
import uuid
from datetime import datetime, timezone

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.deps import get_current_user, get_db
from app.main import app
from app.models import Candidate, Job, JobCandidate


@pytest.fixture()
def db_session():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()
    os.close(fd)
    os.unlink(db_path)


@pytest.fixture()
def client(db_session):
    def override():
        Session = sessionmaker(bind=db_session.get_bind())
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "user-a",
        "email": "a@test.com",
    }
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _uid():
    return str(uuid.uuid4())


def _seed_job(db, *, title, created_at, owner="user-a"):
    job = Job(
        id=_uid(),
        title=title,
        description=f"Descripción {title}",
        owner_sub=owner,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _assign_candidates(db, job, count, *, owner="user-a"):
    for index in range(count):
        candidate = Candidate(
            id=_uid(),
            name=f"Candidate {job.title} {index}",
            owner_sub=owner,
        )
        db.add(candidate)
        db.flush()
        db.add(
            JobCandidate(
                id=_uid(),
                job_id=job.id,
                candidate_id=candidate.id,
            )
        )
    db.commit()


def _seed_listing(db):
    dates = [
        datetime(2026, 9, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 2, tzinfo=timezone.utc),
        datetime(2026, 9, 3, tzinfo=timezone.utc),
        datetime(2026, 9, 4, tzinfo=timezone.utc),
    ]
    backend = _seed_job(db, title="Backend Developer", created_at=dates[0])
    frontend = _seed_job(db, title="Frontend Developer", created_at=dates[1])
    data = _seed_job(db, title="Data Engineer", created_at=dates[2])
    design = _seed_job(db, title="Product Designer", created_at=dates[3])
    _seed_job(db, title="Other tenant", created_at=dates[3], owner="user-b")

    _assign_candidates(db, backend, 1)
    _assign_candidates(db, frontend, 3)
    _assign_candidates(db, data, 2)
    _assign_candidates(db, design, 0)

    # A foreign-tenant candidate linked to this job must not inflate user-a's count.
    _assign_candidates(db, design, 1, owner="user-b")


def test_jobs_page_orders_by_candidate_count_before_paginating(client, db_session):
    _seed_listing(db_session)

    response = client.get(
        "/api/jobs/page",
        params={"page": 1, "page_size": 2, "sort": "candidates_desc"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 4
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert payload["total_pages"] == 2
    assert [item["title"] for item in payload["items"]] == [
        "Frontend Developer",
        "Data Engineer",
    ]
    assert [item["candidate_count"] for item in payload["items"]] == [3, 2]


def test_jobs_page_supports_oldest_first_and_title_search(client, db_session):
    _seed_listing(db_session)

    oldest = client.get(
        "/api/jobs/page",
        params={"page": 1, "page_size": 12, "sort": "created_asc"},
    )
    assert oldest.status_code == 200
    assert [item["title"] for item in oldest.json()["items"]] == [
        "Backend Developer",
        "Frontend Developer",
        "Data Engineer",
        "Product Designer",
    ]

    searched = client.get(
        "/api/jobs/page",
        params={"page": 1, "page_size": 12, "sort": "created_desc", "q": "data"},
    )
    assert searched.status_code == 200
    assert searched.json()["total"] == 1
    assert [item["title"] for item in searched.json()["items"]] == ["Data Engineer"]


def test_jobs_page_rejects_unsupported_sort(client, db_session):
    _seed_listing(db_session)

    response = client.get(
        "/api/jobs/page",
        params={"page": 1, "page_size": 12, "sort": "title_desc"},
    )

    assert response.status_code == 422
