"""Full synchronization contracts for the ASIATI Resume Agent."""

from __future__ import annotations

from datetime import datetime, timezone

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


def test_duplicate_same_candidate_same_job_keeps_only_newest_active_application():
    engine, db = _db()
    try:
        job = Job(title="Operations Coordinator", description="Ops", owner_sub="owner-1")
        candidate = Candidate(name="Edwar Lisandro", owner_sub="owner-1", metadata_={})
        db.add_all([job, candidate])
        db.flush()

        old_event = CandidateIngestionEvent(
            owner_sub="owner-1",
            source="EMAIL",
            provider="INDEED",
            source_account="gmail",
            external_id="old-message",
            status="RECEIVED",
            job_id=job.id,
            candidate_id=candidate.id,
            raw_metadata={"internal_date_ms": 1000},
        )
        new_event = CandidateIngestionEvent(
            owner_sub="owner-1",
            source="EMAIL",
            provider="INDEED",
            source_account="gmail",
            external_id="new-message",
            status="RECEIVED",
            job_id=job.id,
            candidate_id=candidate.id,
            raw_metadata={"internal_date_ms": 2000},
        )
        db.add_all([old_event, new_event])
        db.flush()
        old_task = IndeedEmailResumeTask(
            owner_sub="owner-1",
            ingestion_event_id=old_event.id,
            job_id=job.id,
            candidate_name="Edwar Lisandro",
            job_title=job.title,
            status="WAITING_DOWNLOAD",
        )
        new_task = IndeedEmailResumeTask(
            owner_sub="owner-1",
            ingestion_event_id=new_event.id,
            job_id=job.id,
            candidate_name="EDWAR LISANDRO",
            job_title=job.title,
            status="WAITING_DOWNLOAD",
        )
        db.add_all([old_task, new_task])
        db.commit()

        result = indeed_agent_sync.compact_duplicate_application_tasks(
            db,
            owner_sub="owner-1",
        )

        db.refresh(old_task)
        db.refresh(new_task)
        assert result["superseded"] == 1
        assert old_task.status == "IGNORED"
        assert old_task.last_error_code == "SUPERSEDED_BY_NEWER_APPLICATION"
        assert new_task.status == "WAITING_DOWNLOAD"
    finally:
        db.close()
        engine.dispose()


def test_same_candidate_name_in_different_jobs_is_not_collapsed():
    engine, db = _db()
    try:
        first_job = Job(title="Backend Developer", description="API", owner_sub="owner-1")
        second_job = Job(title="Frontend Developer", description="React", owner_sub="owner-1")
        candidate = Candidate(name="Ana Perez", owner_sub="owner-1", metadata_={})
        db.add_all([first_job, second_job, candidate])
        db.flush()

        for index, job in enumerate((first_job, second_job), start=1):
            event = CandidateIngestionEvent(
                owner_sub="owner-1",
                source="EMAIL",
                provider="INDEED",
                source_account="gmail",
                external_id=f"message-{index}",
                status="RECEIVED",
                job_id=job.id,
                candidate_id=candidate.id,
                raw_metadata={"internal_date_ms": index * 1000},
            )
            db.add(event)
            db.flush()
            db.add(
                IndeedEmailResumeTask(
                    owner_sub="owner-1",
                    ingestion_event_id=event.id,
                    job_id=job.id,
                    candidate_name="Ana Perez",
                    job_title=job.title,
                    status="WAITING_DOWNLOAD",
                )
            )
        db.commit()

        result = indeed_agent_sync.compact_duplicate_application_tasks(
            db,
            owner_sub="owner-1",
        )

        assert result["superseded"] == 0
        assert db.query(IndeedEmailResumeTask).filter_by(status="WAITING_DOWNLOAD").count() == 2
    finally:
        db.close()
        engine.dispose()


def test_candidate_ambiguity_stays_attention_during_normal_incremental_sync():
    engine, db = _db()
    try:
        job = Job(title="Operations Coordinator", description="Ops", owner_sub="owner-1")
        db.add(job)
        db.flush()
        event = CandidateIngestionEvent(
            owner_sub="owner-1",
            source="EMAIL",
            provider="INDEED",
            source_account="gmail",
            external_id="ambiguous-message",
            status="NEEDS_REVIEW",
            job_id=job.id,
            raw_metadata={"internal_date_ms": 3000},
        )
        db.add(event)
        db.flush()
        task = IndeedEmailResumeTask(
            owner_sub="owner-1",
            ingestion_event_id=event.id,
            job_id=job.id,
            candidate_name="Edwar Lisandro",
            job_title=job.title,
            status="NEEDS_HUMAN",
            attempt_count=2,
            last_error_code="INDEED_CANDIDATE_AMBIGUOUS",
        )
        db.add(task)
        db.commit()

        result = indeed_agent_sync.compact_duplicate_application_tasks(
            db,
            owner_sub="owner-1",
        )

        db.refresh(task)
        assert result["requeued_ambiguity"] == 0
        assert task.status == "NEEDS_HUMAN"
        assert task.attempt_count == 2
        assert task.last_error_code == "INDEED_CANDIDATE_AMBIGUOUS"
    finally:
        db.close()
        engine.dispose()


def test_reconciliation_prefers_latest_indeed_application_link():
    engine, db = _db()
    try:
        job = Job(title="Operations Coordinator", description="Ops", owner_sub="owner-1")
        candidate = Candidate(name="Edwar Lisandro", owner_sub="owner-1", metadata_={})
        db.add_all([job, candidate])
        db.flush()
        old_link = IndeedCandidateLink(
            owner_sub="owner-1",
            candidate_id=candidate.id,
            job_id=job.id,
            asset_id="asset-old",
            source_name="Indeed",
            staged_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        new_link = IndeedCandidateLink(
            owner_sub="owner-1",
            candidate_id=candidate.id,
            job_id=job.id,
            asset_id="asset-new",
            source_name="Indeed",
            staged_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
        )
        db.add_all([old_link, new_link])
        db.flush()
        db.add_all([
            IndeedResumeIngestion(
                owner_sub="owner-1",
                candidate_link_id=old_link.id,
                status="FAILED",
            ),
            IndeedResumeIngestion(
                owner_sub="owner-1",
                candidate_link_id=new_link.id,
                status="FAILED",
            ),
        ])
        db.commit()

        result = indeed_agent_sync.reconcile_existing_indeed_candidates(
            db,
            owner_sub="owner-1",
        )

        assert result["scanned"] == 1
        task = db.query(IndeedEmailResumeTask).one()
        event = db.query(CandidateIngestionEvent).filter_by(id=task.ingestion_event_id).one()
        assert event.raw_metadata["indeed_candidate_link_id"] == new_link.id
    finally:
        db.close()
        engine.dispose()


def test_sync_one_page_uses_small_default_page_to_avoid_agent_timeout(monkeypatch):
    engine, db = _db()
    seen = {}
    reconciled = {"calls": 0}
    try:
        def fake_sync_mailbox(*args, **kwargs):
            seen["max_results"] = kwargs.get("max_results")
            return {
                "mode": "INCREMENTAL",
                "discovered": 0,
                "created": 0,
                "existing": 0,
                "needs_review": 0,
                "skipped": 0,
                "cursor_value": "123",
            }

        monkeypatch.setattr(
            indeed_agent_sync.gmail_integration,
            "sync_mailbox",
            fake_sync_mailbox,
        )

        def unexpected_reconciliation(*args, **kwargs):
            reconciled["calls"] += 1
            raise AssertionError("incremental no-op must not scan every candidate")

        monkeypatch.setattr(
            indeed_agent_sync,
            "reconcile_existing_indeed_candidates",
            unexpected_reconciliation,
        )

        result = indeed_agent_sync.sync_one_page(
            db,
            owner_sub="owner-1",
            mailbox_client=object(),
        )

        assert seen["max_results"] == 20
        assert reconciled["calls"] == 0
        assert result["has_more"] is False
        assert result["reconcile_scanned"] == 0
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
