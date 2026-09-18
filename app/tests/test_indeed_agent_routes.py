"""HTTP contracts for the least-privilege Indeed resume agent."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.models import IndeedJobLink, Job
from app.db import Base
from app.deps import get_db
from app.domains.candidate_ingestion.indeed_agent_auth import (
    AgentPrincipal,
    get_indeed_resume_agent_principal,
)
from app.domains.candidate_ingestion.models import (
    CandidateIngestionEvent,
    IndeedEmailResumeTask,
)
from app.main import app


@pytest.fixture()
def api():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_indeed_resume_agent_principal] = (
        lambda: AgentPrincipal(owner_sub="owner-a")
    )
    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def _task(db: Session, *, owner_sub: str, status: str = "WAITING_DOWNLOAD"):
    event = CandidateIngestionEvent(
        owner_sub=owner_sub,
        source="EMAIL",
        provider="INDEED",
        source_account="talent@example.com",
        external_id=f"gmail-{owner_sub}-{status}",
        status="RECEIVED",
        raw_metadata={"gmail_message_id": f"gmail-{owner_sub}-{status}"},
    )
    db.add(event)
    db.flush()
    task = IndeedEmailResumeTask(
        owner_sub=owner_sub,
        ingestion_event_id=event.id,
        candidate_name="Candidate",
        job_title="Designer",
        status=status,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def test_empty_owner_scoped_queue_returns_204(api):
    client, db = api
    _task(db, owner_sub="owner-b")

    response = client.post("/api/agents/indeed-resume/claim")

    assert response.status_code == 204
    assert response.content == b""


def test_stats_are_owner_scoped(api):
    client, db = api
    _task(db, owner_sub="owner-a")
    _task(db, owner_sub="owner-b")

    response = client.get("/api/agents/indeed-resume/stats")

    assert response.status_code == 200
    assert response.json()["pending"] == 1
    assert sum(response.json().values()) == 1


def test_mutating_other_owner_task_returns_404(api):
    client, db = api
    task = _task(db, owner_sub="owner-b", status="CLAIMED")
    task.lease_token = "owner-b-lease"
    task.lease_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    db.commit()

    response = client.post(
        f"/api/agents/indeed-resume/{task.id}/heartbeat",
        headers={"X-ASIATI-Lease-Token": "owner-b-lease"},
    )

    assert response.status_code == 404


def test_wrong_lease_token_returns_409(api):
    client, db = api
    task = _task(db, owner_sub="owner-a", status="CLAIMED")
    task.lease_token = "current-lease"
    task.lease_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    db.commit()

    response = client.post(
        f"/api/agents/indeed-resume/{task.id}/heartbeat",
        headers={"X-ASIATI-Lease-Token": "stale-lease"},
    )

    assert response.status_code == 409
    assert "lease" in response.json()["detail"].casefold()


def test_claim_serializes_ephemeral_resume_url_and_lease(api, monkeypatch):
    from app.domains.candidate_ingestion import indeed_email_agent_service as service

    client, _ = api

    class Claimed:
        task_id = "task-1"
        candidate_name = "Wendy Dayanna Marquez Rincon"
        job_title = "Analista de Automatizacion e IA"
        resume_url = "https://secure.indeed.com/resume/temporary"
        lease_token = "opaque-lease"
        lease_expires_at = datetime(2026, 9, 17, 23, 10, tzinfo=timezone.utc)

    monkeypatch.setattr(
        service,
        "claim_next_task_with_resume_url",
        lambda db, *, owner_sub: Claimed(),
        raising=False,
    )

    response = client.post("/api/agents/indeed-resume/claim")

    assert response.status_code == 200
    assert response.json() == {
        "task_id": "task-1",
        "candidate_name": "Wendy Dayanna Marquez Rincon",
        "job_title": "Analista de Automatizacion e IA",
        "resume_url": "https://secure.indeed.com/resume/temporary",
        "lease_token": "opaque-lease",
        "lease_expires_at": "2026-09-17T23:10:00Z",
    }


def test_claim_preserves_specific_parser_failure_code(api, monkeypatch):
    from app.domains.candidate_ingestion import indeed_email_agent_service as service
    from app.integrations.email_ingestion.indeed_email_parser import InvalidIndeedMessage

    client, db = api
    task = _task(db, owner_sub="owner-a")

    class Mailbox:
        def get_message(self, message_id):
            return {"id": message_id, "payload": {"headers": []}}

    def fail_parser(*args, **kwargs):
        raise InvalidIndeedMessage("INDEED_APPLICATION_FIELDS_MISSING")

    monkeypatch.setattr(service, "parse_indeed_application_email", fail_parser)
    monkeypatch.setattr(service, "_gmail_client_from_oauth", lambda: Mailbox())

    response = client.post("/api/agents/indeed-resume/claim")

    assert response.status_code == 502
    db.refresh(task)
    assert task.status == "NEEDS_HUMAN"
    assert task.last_error_code == "INDEED_APPLICATION_FIELDS_MISSING"


def test_claim_historical_task_auto_creates_and_links_indeed_job(api, monkeypatch):
    from app.domains.candidate_ingestion import indeed_email_agent_service as service

    client, db = api
    task = _task(db, owner_sub="owner-a")

    class Mailbox:
        def get_message(self, message_id):
            return {"id": message_id}

    class Parsed:
        message_id = "gmail-owner-a-WAITING_DOWNLOAD"
        thread_id = "thread-1"
        sender = "conversation@indeedemail.com"
        subject = "CESAR ARCILA se postuló"
        candidate_name = "CESAR ARCILA"
        job_title = "Líder de Contact Center Comercial"
        external_job_id = "JK-CESAR-123"
        resume_url = "https://employers.indeed.com/resume/cesar"
        internal_date_ms = None

    monkeypatch.setattr(service, "_gmail_client_from_oauth", lambda: Mailbox())
    monkeypatch.setattr(
        service,
        "parse_indeed_application_email",
        lambda *args, **kwargs: Parsed(),
    )

    response = client.post("/api/agents/indeed-resume/claim")

    assert response.status_code == 200
    assert response.json()["candidate_name"] == "CESAR ARCILA"
    assert response.json()["job_title"] == "Líder de Contact Center Comercial"

    db.refresh(task)
    assert task.job_id is not None
    assert task.job_title == "Líder de Contact Center Comercial"

    job = db.query(Job).filter(Job.id == task.job_id).one()
    assert job.title == "Líder de Contact Center Comercial"
    assert job.owner_sub == "owner-a"

    link = db.query(IndeedJobLink).filter(IndeedJobLink.job_id == job.id).one()
    assert link.discovery_key == "posting:jk-cesar-123"
    assert link.sourced_posting_id == "JK-CESAR-123"
    assert link.external_status["auto_created"] is True
