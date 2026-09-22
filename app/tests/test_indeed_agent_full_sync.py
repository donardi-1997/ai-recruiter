"""Full synchronization contracts for the ASIATI Resume Agent."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
import app.domains.indeed.resume_models  # noqa: F401
from app.db import Base
from app.domains.candidate_ingestion import indeed_agent_sync
from app.domains.candidate_ingestion.models import (
    CandidateIngestionEvent,
    IndeedEmailResumeTask,
)
from app.domains.indeed.resume_models import IndeedResumeIngestion
from app.models import Candidate, IndeedCandidateLink, Job


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def _seed_link(db: Session, *, owner_sub="owner-1", name="Ada Candidate", status=None, canonical=None):
    job = Job(
        title="Cloud Engineer",
        description="AWS",
        owner_sub=owner_sub,
    )
    candidate = Candidate(
        name=name,
        owner_sub=owner_sub,
        metadata_={},
    )
    db.add_all([job, candidate])
    db.flush()
    link = IndeedCandidateLink(
        owner_sub=owner_sub,
        candidate_id=candidate.id,
        job_id=job.id,
        asset_id=f"asset-{owner_sub}-{name}",
        source_name="Indeed",
    )
    db.add(link)
    db.flush()
    resume = None
    if status is not None:
        resume = IndeedResumeIngestion(
            owner_sub=owner_sub,
            candidate_link_id=link.id,
            status=status,
            canonical_s3_key=canonical,
        )
        db.add(resume)
    db.commit()
    return job, candidate, link, resume


def test_failed_provider_resume_gets_one_lookup_only_agent_task():
    engine, db = _db()
    try:
        job, candidate, link, _ = _seed_link(db, status="FAILED")

        first = indeed_agent_sync.reconcile_existing_indeed_candidates(
            db,
            owner_sub="owner-1",
        )
        second = indeed_agent_sync.reconcile_existing_indeed_candidates(
            db,
            owner_sub="owner-1",
        )

        assert first["jobs_scanned"] == 1
        assert first["scanned"] == 1
        assert first["queued"] == 1
        assert second["queued"] == 0
        assert second["covered"] == 1

        task = db.query(IndeedEmailResumeTask).one()
        event = db.query(CandidateIngestionEvent).filter_by(id=task.ingestion_event_id).one()
        assert task.job_id == job.id
        assert task.candidate_name == candidate.name
        assert task.status == "WAITING_DOWNLOAD"
        assert event.candidate_id == candidate.id
        assert event.job_id == job.id
        assert event.raw_metadata["resume_agent_lookup_only"] is True
        assert event.raw_metadata["indeed_candidate_link_id"] == link.id
    finally:
        db.close()
        engine.dispose()


def test_completed_or_active_provider_resume_is_not_duplicated_locally():
    engine, db = _db()
    try:
        _seed_link(
            db,
            name="Completed Candidate",
            status="COMPLETED",
            canonical="documents/completed.pdf",
        )
        _seed_link(
            db,
            name="Pending Candidate",
            status="EVALUATING",
        )

        result = indeed_agent_sync.reconcile_existing_indeed_candidates(
            db,
            owner_sub="owner-1",
        )

        assert result["scanned"] == 2
        assert result["ready"] == 1
        assert result["provider_pending"] == 1
        assert result["queued"] == 0
        assert db.query(IndeedEmailResumeTask).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_reconciliation_is_owner_scoped():
    engine, db = _db()
    try:
        _seed_link(db, owner_sub="owner-1", status="FAILED")
        _seed_link(db, owner_sub="owner-2", status="FAILED")

        result = indeed_agent_sync.reconcile_existing_indeed_candidates(
            db,
            owner_sub="owner-1",
        )

        assert result["scanned"] == 1
        tasks = db.query(IndeedEmailResumeTask).all()
        assert len(tasks) == 1
        assert tasks[0].owner_sub == "owner-1"
    finally:
        db.close()
        engine.dispose()


def test_sync_one_page_reports_bootstrap_continuation(monkeypatch):
    engine, db = _db()
    try:
        monkeypatch.setattr(
            indeed_agent_sync.gmail_integration,
            "sync_mailbox",
            lambda *args, **kwargs: {
                "mode": "FULL",
                "discovered": 100,
                "created": 40,
                "existing": 50,
                "needs_review": 2,
                "skipped": 8,
                "cursor_value": "GMAIL_BOOTSTRAP_V1:{\"page_token\":\"next\"}",
            },
        )
        monkeypatch.setattr(
            indeed_agent_sync,
            "reconcile_existing_indeed_candidates",
            lambda *args, **kwargs: {
                "jobs_scanned": 4,
                "scanned": 12,
                "ready": 4,
                "provider_pending": 3,
                "covered": 2,
                "queued": 3,
            },
        )

        result = indeed_agent_sync.sync_one_page(
            db,
            owner_sub="owner-1",
            mailbox_client=object(),
        )

        assert result["has_more"] is True
        assert result["discovered"] == 100
        assert result["reconcile_jobs"] == 4
        assert result["reconcile_scanned"] == 12
        assert result["reconcile_queued"] == 3
    finally:
        db.close()
        engine.dispose()
