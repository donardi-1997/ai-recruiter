"""Candidate Sync must durably hand Indeed resumes to asynchronous processing."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import IndeedSettings
from app.db import Base
from app.domains.indeed import service
from app.domains.indeed.resume_models import IndeedResumeIngestion
from app.models import IndeedJobLink, Job


def _settings():
    return IndeedSettings(
        enabled=True,
        client_id="client",
        client_secret="secret",
        employer_id="employer-1",
        scope="employer_access employer.hosted_job",
        source_name="Asiati Talent",
        company_name="Asiati",
        token_url="https://apis.indeed.com/oauth/v2/tokens",
        graphql_url="https://apis.indeed.com/graphql",
        request_timeout_seconds=10.0,
        careers_base_url="https://www.asiaticorp.com/jobs",
    )


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_job(db):
    job = Job(
        title="Country Manager Chile",
        description="Lead the Chile operation and expand the local market.",
        owner_sub="owner-1",
    )
    db.add(job)
    db.flush()
    db.add(
        IndeedJobLink(
            job_id=job.id,
            owner_sub="owner-1",
            sourced_posting_id="sourced-1",
            employer_job_id="employer-job-1",
        )
    )
    db.commit()
    return job


def _asset(*, asset_id="asset-1", resume=True):
    resume_value = (
        {"pdf": {"name": "ana.pdf", "url": "https://resume.invalid/ana.pdf?sig=fake"}}
        if resume
        else None
    )
    return {
        "id": asset_id,
        "metadata": {
            "stagedAt": "2026-09-15T20:00:00Z",
            "stagedTest": True,
            "completeSourceAttribution": {"name": "Indeed"},
        },
        "contact": {
            "candidate": {
                "email": "ana@example.com",
                "name": "Ana Perez",
                "phone": "+573001112233",
                "resume": resume_value,
            },
            "job": {"sourcedPostingId": "sourced-1"},
            "tracking": {},
        },
    }


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def execute(self, _query, variables=None):
        return self.responses.pop(0)


def _response(asset, token="next-token"):
    return {
        "atsSyncCandidateSync": {
            "fetchAssets": {
                "assets": [asset],
                "token": token,
            }
        }
    }


def test_candidate_sync_creates_and_dispatches_one_resume_task(db_session, monkeypatch):
    _seed_job(db_session)
    sent = []
    from app.domains.indeed import candidates

    monkeypatch.setattr(
        candidates.queue,
        "send_indeed_resume_ingestion",
        lambda task_id: sent.append(task_id) or "message-1",
    )

    service.sync_candidates(
        db_session,
        owner_sub="owner-1",
        client=FakeClient([_response(_asset())]),
        settings=_settings(),
    )

    task = db_session.query(IndeedResumeIngestion).one()
    assert sent == [task.id]
    assert task.status == "PENDING"
    assert task.queue_dispatched_at is not None


def test_candidate_sync_without_resume_does_not_create_resume_task(db_session, monkeypatch):
    _seed_job(db_session)
    sent = []
    from app.domains.indeed import candidates

    monkeypatch.setattr(
        candidates.queue,
        "send_indeed_resume_ingestion",
        lambda task_id: sent.append(task_id),
    )

    service.sync_candidates(
        db_session,
        owner_sub="owner-1",
        client=FakeClient([_response(_asset(resume=False))]),
        settings=_settings(),
    )

    assert db_session.query(IndeedResumeIngestion).count() == 0
    assert sent == []


def test_queue_failure_keeps_candidate_sync_successful_and_task_repairable(db_session, monkeypatch):
    _seed_job(db_session)
    from app.domains.indeed import candidates

    def fail(_task_id):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(candidates.queue, "send_indeed_resume_ingestion", fail)

    result = service.sync_candidates(
        db_session,
        owner_sub="owner-1",
        client=FakeClient([_response(_asset())]),
        settings=_settings(),
    )

    task = db_session.query(IndeedResumeIngestion).one()
    assert result["created"] == 1
    assert task.queue_dispatched_at is None
    assert task.status == "PENDING"


def test_repeated_asset_does_not_duplicate_or_redispatch_completed_handoff(db_session, monkeypatch):
    _seed_job(db_session)
    sent = []
    from app.domains.indeed import candidates

    monkeypatch.setattr(
        candidates.queue,
        "send_indeed_resume_ingestion",
        lambda task_id: sent.append(task_id) or "message-1",
    )
    client = FakeClient([
        _response(_asset(), token="ack-1"),
        _response(_asset(), token="ack-2"),
    ])

    service.sync_candidates(db_session, owner_sub="owner-1", client=client, settings=_settings())
    service.sync_candidates(db_session, owner_sub="owner-1", client=client, settings=_settings())

    assert db_session.query(IndeedResumeIngestion).count() == 1
    assert len(sent) == 1
