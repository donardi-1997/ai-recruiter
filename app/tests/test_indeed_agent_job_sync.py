"""Indeed Employers vacancy refresh contracts for the desktop Resume Agent."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.domains.candidate_ingestion import indeed_job_sync
from app.domains.candidate_ingestion.models import (
    CandidateIngestionEvent,
    IndeedEmailResumeTask,
)
from app.models import IndeedJobLink, Job


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def snapshot(**overrides):
    value = {
        "external_job_key": "abc-123",
        "title": "Cloud Engineer",
        "description": "Original Indeed description with AWS and Terraform.",
        "status": "OPEN",
        "location": "Bogotá, Cundinamarca",
        "posted_at": "2026-09-20T10:00:00Z",
    }
    value.update(overrides)
    return value


def test_new_vacancy_requires_stable_identity_and_non_empty_description():
    engine, db = _db()
    try:
        result = indeed_job_sync.sync_vacancy_snapshots(
            db,
            owner_sub="owner-1",
            snapshots=[
                snapshot(external_job_key=""),
                snapshot(external_job_key="missing-desc", description=""),
                snapshot(),
            ],
        )

        assert result["discovered"] == 3
        assert result["created"] == 1
        assert result["missing_identity"] == 1
        assert result["missing_description"] == 1
        job = db.query(Job).one()
        assert job.indeed_description == snapshot()["description"]
        assert job.description == snapshot()["description"]
        assert job.active_description_source == "indeed"
        link = db.query(IndeedJobLink).one()
        assert link.discovery_key == "employer-ui:abc-123"
    finally:
        db.close()
        engine.dispose()


def test_refresh_preserves_active_full_ai_description_and_is_idempotent():
    engine, db = _db()
    try:
        full_ai = "\n\n".join([
            "Descripción optimizada completa.",
            "Tecnologías requeridas\n- AWS\n- Terraform",
            "Responsabilidades\n- Diseñar infraestructura\n- Operar observabilidad",
            "Experiencia específica\n- 5 años en cloud",
        ])
        job = Job(
            title="Cloud Engineer",
            description=full_ai,
            indeed_description="Old Indeed description",
            ai_description=full_ai,
            active_description_source="ai",
            evaluation_profile={},
            evaluation_version=7,
            owner_sub="owner-1",
        )
        db.add(job)
        db.flush()
        db.add(
            IndeedJobLink(
                job_id=job.id,
                owner_sub="owner-1",
                discovery_key="employer-ui:abc-123",
                external_status={"origin": "EMPLOYER_UI"},
            )
        )
        db.commit()

        changed = snapshot(description="New complete Indeed description")
        first = indeed_job_sync.sync_vacancy_snapshots(
            db,
            owner_sub="owner-1",
            snapshots=[changed],
        )
        db.refresh(job)

        assert first["updated"] == 1
        assert job.indeed_description == "New complete Indeed description"
        assert job.ai_description == full_ai
        assert job.description == full_ai
        assert job.active_description_source == "ai"
        assert job.evaluation_version == 7

        second = indeed_job_sync.sync_vacancy_snapshots(
            db,
            owner_sub="owner-1",
            snapshots=[changed],
        )
        assert second["unchanged"] == 1
        assert second["updated"] == 0
    finally:
        db.close()
        engine.dispose()


def test_historical_title_only_vacancy_is_adopted_in_place_when_unambiguous():
    engine, db = _db()
    try:
        job = Job(
            title="Cloud Engineer",
            description=None,
            owner_sub="owner-1",
            evaluation_profile={},
        )
        db.add(job)
        db.commit()
        original_id = job.id

        result = indeed_job_sync.sync_vacancy_snapshots(
            db,
            owner_sub="owner-1",
            snapshots=[snapshot()],
        )

        assert result["reconciled"] == 1
        assert result["created"] == 0
        assert db.query(Job).count() == 1
        db.refresh(job)
        assert job.id == original_id
        assert job.indeed_description == snapshot()["description"]
        assert db.query(IndeedJobLink).filter_by(job_id=original_id).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_empty_refresh_never_erases_existing_indeed_description():
    engine, db = _db()
    try:
        job = Job(
            title="Cloud Engineer",
            description="Stored Indeed description",
            indeed_description="Stored Indeed description",
            active_description_source="indeed",
            evaluation_profile={},
            owner_sub="owner-1",
        )
        db.add(job)
        db.flush()
        db.add(
            IndeedJobLink(
                job_id=job.id,
                owner_sub="owner-1",
                discovery_key="employer-ui:abc-123",
                external_status={"origin": "EMPLOYER_UI"},
            )
        )
        db.commit()

        result = indeed_job_sync.sync_vacancy_snapshots(
            db,
            owner_sub="owner-1",
            snapshots=[snapshot(description="")],
        )
        db.refresh(job)

        assert result["missing_description"] == 1
        assert job.indeed_description == "Stored Indeed description"
        assert job.description == "Stored Indeed description"
    finally:
        db.close()
        engine.dispose()


def test_vacancy_refresh_stays_jobs_only_and_application_repair_is_separate():
    engine, db = _db()
    try:
        event = CandidateIngestionEvent(
            owner_sub="owner-1",
            source="EMAIL",
            provider="INDEED",
            source_account="katherine@example.com",
            external_id="gmail-waiting-1",
            status="NEEDS_REVIEW",
            raw_metadata={
                "gmail_message_id": "gmail-waiting-1",
                "candidate_name": "Ada Candidate",
                "job_title": "Cloud Engineer",
                "external_job_id": "abc-123",
                "internal_date_ms": 1789574400000,
            },
            last_error_code="INDEED_JOB_NOT_SYNCED_YET",
            last_error_message="La vacante de Indeed debe sincronizarse antes de procesar esta postulacion.",
        )
        db.add(event)
        db.commit()

        result = indeed_job_sync.sync_vacancy_snapshots(
            db,
            owner_sub="owner-1",
            snapshots=[snapshot()],
        )

        db.refresh(event)
        assert "applications_recovered" not in result
        assert event.status == "NEEDS_REVIEW"
        assert event.job_id is None
        assert db.query(IndeedEmailResumeTask).count() == 0

        recovered = indeed_job_sync.recover_waiting_applications(
            db,
            owner_sub="owner-1",
        )

        db.refresh(event)
        task = db.query(IndeedEmailResumeTask).filter_by(
            ingestion_event_id=event.id
        ).one()
        job = db.query(Job).one()

        assert recovered == 1
        assert event.status == "RECEIVED"
        assert event.job_id == job.id
        assert event.last_error_code == "RESUME_DOWNLOAD_PENDING"
        assert task.job_id == job.id
        assert task.candidate_name == "Ada Candidate"
        assert task.job_title == "Cloud Engineer"
        assert task.status == "WAITING_DOWNLOAD"

        assert indeed_job_sync.recover_waiting_applications(
            db,
            owner_sub="owner-1",
        ) == 0
        assert db.query(IndeedEmailResumeTask).filter_by(
            ingestion_event_id=event.id
        ).count() == 1
    finally:
        db.close()
        engine.dispose()