"""Contract tests for durable Indeed resume processing."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.db import Base
from app.domains.indeed import resume_repository
from app.domains.indeed.resume_models import IndeedResumeIngestion


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


def _seed_link(db, *, owner_sub="owner-1"):
    candidate = models.Candidate(name="Ana Perez", email="ana@example.com", owner_sub=owner_sub)
    job = models.Job(title="Country Manager", description="Lead the local operation", owner_sub=owner_sub)
    db.add_all([candidate, job])
    db.flush()
    link = models.IndeedCandidateLink(
        owner_sub=owner_sub,
        candidate_id=candidate.id,
        job_id=job.id,
        asset_id="asset-1",
        source_name="Indeed",
        resume_name="ana.pdf",
        resume_url="https://resume.invalid/ana.pdf?signature=secret",
    )
    db.add(link)
    db.commit()
    return candidate, job, link


def test_resume_ingestion_model_has_pending_defaults(db_session):
    _candidate, _job, link = _seed_link(db_session)
    ingestion = IndeedResumeIngestion(owner_sub="owner-1", candidate_link_id=link.id)
    db_session.add(ingestion)
    db_session.commit()
    db_session.refresh(ingestion)

    assert ingestion.status == "PENDING"
    assert ingestion.attempt_count == 0
    assert ingestion.queue_dispatched_at is None
    assert ingestion.resume_sha256 is None
    assert ingestion.canonical_s3_key is None
    assert ingestion.bedrock_ingestion_job_id is None
    assert ingestion.completed_at is None


def test_resume_ingestion_is_one_to_one_with_candidate_link(db_session):
    _candidate, _job, link = _seed_link(db_session)
    first = IndeedResumeIngestion(owner_sub="owner-1", candidate_link_id=link.id)
    db_session.add(first)
    db_session.commit()

    reused = resume_repository.get_or_create_resume_ingestion(
        db_session,
        owner_sub="owner-1",
        candidate_link_id=link.id,
    )

    assert reused.id == first.id
    assert db_session.query(IndeedResumeIngestion).count() == 1


def test_resume_ingestion_repository_is_owner_scoped(db_session):
    _candidate, _job, link = _seed_link(db_session, owner_sub="owner-1")
    ingestion = IndeedResumeIngestion(owner_sub="owner-1", candidate_link_id=link.id)
    db_session.add(ingestion)
    db_session.commit()

    assert resume_repository.get_resume_ingestion(
        db_session,
        ingestion.id,
        owner_sub="owner-1",
    ).id == ingestion.id
    assert resume_repository.get_resume_ingestion(
        db_session,
        ingestion.id,
        owner_sub="owner-2",
    ) is None


def test_resume_ingestion_claim_respects_active_and_stale_leases(db_session):
    _candidate, _job, link = _seed_link(db_session)
    ingestion = IndeedResumeIngestion(owner_sub="owner-1", candidate_link_id=link.id)
    db_session.add(ingestion)
    db_session.commit()

    now = datetime(2026, 9, 15, 17, 0, tzinfo=timezone.utc)
    assert resume_repository.claim_resume_ingestion(
        db_session,
        ingestion_id=ingestion.id,
        token="token-a",
        now=now,
        lease_seconds=300,
    ) is True

    assert resume_repository.claim_resume_ingestion(
        db_session,
        ingestion_id=ingestion.id,
        token="token-b",
        now=now + timedelta(seconds=60),
        lease_seconds=300,
    ) is False

    assert resume_repository.claim_resume_ingestion(
        db_session,
        ingestion_id=ingestion.id,
        token="token-c",
        now=now + timedelta(seconds=301),
        lease_seconds=300,
    ) is True

    db_session.refresh(ingestion)
    assert ingestion.processing_token == "token-c"
    assert ingestion.attempt_count == 2
