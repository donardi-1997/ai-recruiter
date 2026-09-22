"""HTTP contracts for the least-privilege Indeed resume agent."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

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
    payload = response.json()
    assert payload["pending"] == 1
    assert sum(payload[key] for key in ("pending", "claimed", "completed", "needs_human", "retry", "failed")) == 1
    assert payload["last_error_code"] is None
    assert payload["last_error_candidate"] is None
    assert payload["last_error_status"] is None


def test_stats_surface_latest_owner_scoped_error_without_secret_fields(api):
    client, db = api
    owned = _task(db, owner_sub="owner-a", status="FAILED")
    owned.candidate_name = "Alejandra"
    owned.last_error_code = "RESUME_UPLOAD_FAILED"
    other = _task(db, owner_sub="owner-b", status="FAILED")
    other.candidate_name = "Other Owner"
    other.last_error_code = "SHOULD_NOT_LEAK"
    db.commit()
    response = client.get("/api/agents/indeed-resume/stats")
    assert response.status_code == 200
    payload = response.json()
    assert payload["last_error_code"] == "RESUME_UPLOAD_FAILED"
    assert payload["last_error_candidate"] == "Alejandra"
    assert payload["last_error_status"] == "FAILED"
    assert "SHOULD_NOT_LEAK" not in str(payload)


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


def test_resume_upload_route_preserves_docx_filename_and_mime(api, monkeypatch):
    from app.domains.candidate_ingestion import indeed_email_agent_service as service

    client, db = api
    task = _task(db, owner_sub="owner-a", status="CLAIMED")
    task.lease_token = "lease-1"
    task.lease_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    db.commit()
    seen = {}

    def fake_store(db, *, owner_sub, task_id, lease_token, filename, content_type, data):
        seen.update({
            "owner_sub": owner_sub,
            "task_id": task_id,
            "lease_token": lease_token,
            "filename": filename,
            "content_type": content_type,
            "data": data,
        })
        return SimpleNamespace(id="document-1", filename=filename, document_sha256="abc123")

    monkeypatch.setattr(service, "store_resume_document", fake_store)
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    response = client.post(
        f"/api/agents/indeed-resume/{task.id}/resume",
        headers={"X-ASIATI-Lease-Token": "lease-1"},
        files={"file": ("CVAlejandracamachosaenz.docx", b"PK-docx", mime)},
    )
    assert response.status_code == 200
    assert response.json()["filename"] == "CVAlejandracamachosaenz.docx"
    assert seen == {
        "owner_sub": "owner-a",
        "task_id": task.id,
        "lease_token": "lease-1",
        "filename": "CVAlejandracamachosaenz.docx",
        "content_type": mime,
        "data": b"PK-docx",
    }


def test_failure_code_rejects_unbounded_or_freeform_agent_input(api):
    client, db = api
    task = _task(db, owner_sub="owner-a", status="CLAIMED")
    task.lease_token = "lease-1"
    task.lease_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    db.commit()
    response = client.post(
        f"/api/agents/indeed-resume/{task.id}/fail",
        headers={"X-ASIATI-Lease-Token": "lease-1"},
        json={"code": "bad code with spaces"},
    )
    assert response.status_code == 422
    db.refresh(task)
    assert task.status == "CLAIMED"


def test_retry_failed_requeues_only_current_owner_and_resets_terminal_fields(api):
    client, db = api
    owned = _task(db, owner_sub="owner-a", status="FAILED")
    owned.attempt_count = 3
    owned.last_error_code = "RESUME_DOWNLOAD_FAILED"
    owned.last_error_message = "failed"
    owned.completed_at = datetime(2026, 9, 21, tzinfo=timezone.utc)
    owned.lease_token = "stale"
    owned.lease_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    owned.claimed_at = datetime(2026, 9, 20, tzinfo=timezone.utc)
    other = _task(db, owner_sub="owner-b", status="FAILED")
    other.attempt_count = 3
    db.commit()
    response = client.post("/api/agents/indeed-resume/retry-failed")
    assert response.status_code == 200
    assert response.json() == {"status": "WAITING_DOWNLOAD", "requeued": 1}
    db.refresh(owned)
    db.refresh(other)
    assert owned.status == "WAITING_DOWNLOAD"
    assert owned.attempt_count == 0
    assert owned.last_error_code is None
    assert owned.last_error_message is None
    assert owned.completed_at is None
    assert owned.lease_token is None
    assert owned.lease_expires_at is None
    assert owned.claimed_at is None
    assert other.status == "FAILED"
    assert other.attempt_count == 3


def test_retry_attention_requeues_only_current_owner_needs_human(api):
    client, db = api
    owned = _task(db, owner_sub="owner-a", status="NEEDS_HUMAN")
    owned.attempt_count = 2
    owned.last_error_code = "INDEED_UI_REQUIRES_REVIEW"
    owned.last_error_message = "manual review"
    other = _task(db, owner_sub="owner-b", status="NEEDS_HUMAN")
    waiting = _task(db, owner_sub="owner-a", status="WAITING_DOWNLOAD")
    db.commit()
    response = client.post("/api/agents/indeed-resume/retry-attention")
    assert response.status_code == 200
    assert response.json() == {"status": "WAITING_DOWNLOAD", "requeued": 1}
    db.refresh(owned)
    db.refresh(other)
    db.refresh(waiting)
    assert owned.status == "WAITING_DOWNLOAD"
    assert owned.attempt_count == 2
    assert owned.last_error_code is None
    assert owned.last_error_message is None
    assert other.status == "NEEDS_HUMAN"
    assert waiting.status == "WAITING_DOWNLOAD"


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

    monkeypatch.setattr(service, "claim_next_task_with_resume_url", lambda db, *, owner_sub: Claimed(), raising=False)
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


def test_sync_route_is_owner_scoped_and_returns_safe_summary(api, monkeypatch):
    from app.domains.candidate_ingestion import indeed_agent_sync
    client, _ = api
    seen = {}

    def fake_sync(db, *, owner_sub):
        seen["owner_sub"] = owner_sub
        return {
            "mode": "INCREMENTAL",
            "discovered": 3,
            "created": 2,
            "existing": 1,
            "needs_review": 0,
            "skipped": 0,
            "has_more": False,
            "reconcile_jobs": 2,
            "reconcile_scanned": 5,
            "reconcile_ready": 3,
            "reconcile_provider_pending": 1,
            "reconcile_covered": 0,
            "reconcile_queued": 1,
        }

    monkeypatch.setattr(indeed_agent_sync, "sync_one_page", fake_sync)
    response = client.post("/api/agents/indeed-resume/sync")
    assert response.status_code == 200
    assert seen["owner_sub"] == "owner-a"
    assert response.json()["reconcile_queued"] == 1


def test_claim_lookup_only_task_does_not_require_gmail(api):
    client, db = api
    event = CandidateIngestionEvent(
        owner_sub="owner-a",
        source="AGENT",
        provider="INDEED",
        source_account="resume-agent",
        external_id="indeed-candidate-link:1",
        status="RECEIVED",
        raw_metadata={
            "resume_agent_lookup_only": True,
            "candidate_name": "Ada Candidate",
            "job_title": "Cloud Engineer",
        },
    )
    db.add(event)
    db.flush()
    task = IndeedEmailResumeTask(
        owner_sub="owner-a",
        ingestion_event_id=event.id,
        candidate_name="Ada Candidate",
        job_title="Cloud Engineer",
        status="WAITING_DOWNLOAD",
    )
    db.add(task)
    db.commit()
    response = client.post("/api/agents/indeed-resume/claim")
    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_name"] == "Ada Candidate"
    assert payload["job_title"] == "Cloud Engineer"
    assert payload["resume_url"] == "https://employers.indeed.com/candidates"


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


def test_claim_historical_task_reuses_previously_synced_indeed_job(api, monkeypatch):
    from app.domains.candidate_ingestion import indeed_email_agent_service as service

    client, db = api
    job = Job(
        title="Líder de Contact Center Comercial",
        description="Descripción completa de Indeed",
        indeed_description="Descripción completa de Indeed",
        active_description_source="indeed",
        owner_sub="owner-a",
    )
    db.add(job)
    db.flush()
    db.add(
        IndeedJobLink(
            job_id=job.id,
            owner_sub="owner-a",
            discovery_key="employer-ui:provider-job-cesar",
            sourced_posting_id="JK-CESAR-123",
            external_status={"origin": "EMPLOYER_UI"},
        )
    )
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
    monkeypatch.setattr(service, "parse_indeed_application_email", lambda *args, **kwargs: Parsed())
    response = client.post("/api/agents/indeed-resume/claim")
    assert response.status_code == 200
    assert response.json()["candidate_name"] == "CESAR ARCILA"
    assert response.json()["job_title"] == "Líder de Contact Center Comercial"

    db.refresh(task)
    assert task.job_id == job.id
    assert task.job_title == "Líder de Contact Center Comercial"
    assert db.query(Job).filter(Job.owner_sub == "owner-a").count() == 1
    link = db.query(IndeedJobLink).filter(IndeedJobLink.job_id == job.id).one()
    assert link.sourced_posting_id == "JK-CESAR-123"
    assert link.external_status["origin"] == "EMPLOYER_UI"
