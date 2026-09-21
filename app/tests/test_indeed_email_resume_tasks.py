"""Persistence contracts for durable Indeed email resume-download tasks."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models  # noqa: F401 - register shared FK target tables
from app.db import Base
from app.domains.candidate_ingestion import indeed_email_agent_service
from app.domains.candidate_ingestion.models import CandidateIngestionEvent


def _task_model():
    module = importlib.import_module("app.domains.candidate_ingestion.models")
    task_model = getattr(module, "IndeedEmailResumeTask", None)
    if task_model is None:
        pytest.fail("IndeedEmailResumeTask model is missing")
    return task_model


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def _event(db: Session, external_id: str = "gmail-1") -> CandidateIngestionEvent:
    event = CandidateIngestionEvent(
        owner_sub="owner-1",
        source="EMAIL",
        provider="INDEED",
        source_account="hr@example.com",
        external_id=external_id,
        status="RECEIVED",
        raw_metadata={"subject": "Indeed application"},
    )
    db.add(event)
    db.flush()
    return event


def test_resume_task_table_exists_and_allows_unresolved_job():
    task_model = _task_model()
    engine, db = _db()
    try:
        assert "indeed_email_resume_tasks" in set(inspect(engine).get_table_names())
        event = _event(db)
        task = task_model(
            owner_sub="owner-1",
            ingestion_event_id=event.id,
            candidate_name="Ana Perez",
            job_title="Country Manager Chile",
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        assert task.job_id is None
        assert task.status == "WAITING_DOWNLOAD"
        assert task.attempt_count == 0
        assert task.lease_token is None
        assert task.lease_expires_at is None
        assert task.claimed_at is None
        assert task.available_at is None
        assert task.completed_at is None
    finally:
        db.close()
        engine.dispose()


def test_resume_task_is_unique_per_ingestion_event():
    task_model = _task_model()
    engine, db = _db()
    try:
        event = _event(db)
        db.add(
            task_model(
                owner_sub="owner-1",
                ingestion_event_id=event.id,
                candidate_name="Ana Perez",
                job_title="Country Manager Chile",
            )
        )
        db.commit()

        db.add(
            task_model(
                owner_sub="owner-1",
                ingestion_event_id=event.id,
                candidate_name="Ana Perez",
                job_title="Country Manager Chile",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.close()
        engine.dispose()


def test_migration_011_is_additive_and_revises_010():
    migration = Path("app/migrations/versions/011_indeed_email_resume_agent.py")

    assert migration.exists()
    text = migration.read_text(encoding="utf-8")
    assert 'revision = "011"' in text
    assert 'down_revision = "010"' in text
    assert '"indeed_email_resume_tasks"' in text
    assert '"uq_indeed_email_resume_task_event"' in text
    assert '"idx_indeed_email_resume_task_claim"' in text
    assert '"idx_indeed_email_resume_task_owner_status"' in text


def test_reactivate_one_archived_task_is_owner_scoped_and_idempotent():
    task_model = _task_model()
    engine, db = _db()
    try:
        event = _event(db, external_id="gmail-archived")
        task = task_model(
            owner_sub="owner-1",
            ingestion_event_id=event.id,
            candidate_name="Ana Perez",
            job_title="Country Manager Chile",
            status="IGNORED",
            last_error_code="HISTORICAL_BOOTSTRAP_SKIPPED",
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        first = indeed_email_agent_service.reactivate_one_archived_task(
            db,
            owner_sub="owner-1",
        )
        db.refresh(task)

        assert first["reactivated"] is True
        assert first["task_id"] == task.id
        assert task.status == "WAITING_DOWNLOAD"
        assert task.last_error_code is None

        second = indeed_email_agent_service.reactivate_one_archived_task(
            db,
            owner_sub="owner-1",
        )

        assert second["reactivated"] is False
        assert second["task_id"] == task.id
        assert second["status"] == "WAITING_DOWNLOAD"
    finally:
        db.close()
        engine.dispose()


def test_failed_smoke_task_can_be_retried_with_fresh_attempt_budget():
    task_model = _task_model()
    engine, db = _db()
    try:
        event = _event(db, external_id="gmail-failed")
        task = task_model(
            owner_sub="owner-1",
            ingestion_event_id=event.id,
            candidate_name="CESAR ARCILA",
            job_title="Líder de Contact Center Comercial",
            status="FAILED",
            attempt_count=3,
            last_error_code="RESUME_DOWNLOAD_FAILED",
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        active = indeed_email_agent_service.get_active_smoke_task(
            db,
            owner_sub="owner-1",
        )
        assert active["task_id"] == task.id
        assert active["status"] == "FAILED"
        assert active["last_error_code"] == "RESUME_DOWNLOAD_FAILED"

        retried = indeed_email_agent_service.retry_active_needs_human_task(
            db,
            owner_sub="owner-1",
        )
        db.refresh(task)

        assert retried["retried"] is True
        assert retried["task_id"] == task.id
        assert task.status == "WAITING_DOWNLOAD"
        assert task.attempt_count == 0
        assert task.completed_at is None
        assert task.last_error_code is None
        assert task.last_error_message is None
        assert task.lease_token is None
        assert task.lease_expires_at is None
    finally:
        db.close()
        engine.dispose()


def test_failed_smoke_task_blocks_activation_of_a_third_archived_candidate():
    task_model = _task_model()
    engine, db = _db()
    try:
        failed_event = _event(db, external_id="gmail-failed-existing")
        failed = task_model(
            owner_sub="owner-1",
            ingestion_event_id=failed_event.id,
            candidate_name="CESAR ARCILA",
            job_title="Líder de Contact Center Comercial",
            status="FAILED",
            attempt_count=3,
            last_error_code="RESUME_DOWNLOAD_FAILED",
        )
        archived_event = _event(db, external_id="gmail-archived-next")
        archived = task_model(
            owner_sub="owner-1",
            ingestion_event_id=archived_event.id,
            candidate_name="Otro Candidato",
            job_title="Otra Vacante",
            status="IGNORED",
            last_error_code="HISTORICAL_BOOTSTRAP_SKIPPED",
        )
        db.add_all([failed, archived])
        db.commit()

        result = indeed_email_agent_service.reactivate_one_archived_task(
            db,
            owner_sub="owner-1",
        )
        db.refresh(archived)

        assert result["reactivated"] is False
        assert result["task_id"] == failed.id
        assert result["status"] == "FAILED"
        assert archived.status == "IGNORED"
    finally:
        db.close()
        engine.dispose()
