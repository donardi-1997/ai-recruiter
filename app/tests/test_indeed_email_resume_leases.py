"""Contracts for leased, crash-safe Indeed email resume-download tasks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.domains.candidate_ingestion.models import (
    CandidateIngestionEvent,
    IndeedEmailResumeTask,
)

NOW = datetime(2026, 9, 17, 18, 0, tzinfo=timezone.utc)


def _service():
    from app.domains.candidate_ingestion import indeed_email_agent_service

    return indeed_email_agent_service


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def _task(
    db: Session,
    *,
    suffix: str,
    owner_sub: str = "owner-1",
    status: str = "WAITING_DOWNLOAD",
    created_at: datetime | None = None,
    available_at: datetime | None = None,
    lease_token: str | None = None,
    lease_expires_at: datetime | None = None,
    attempt_count: int = 0,
) -> IndeedEmailResumeTask:
    event = CandidateIngestionEvent(
        owner_sub=owner_sub,
        source="EMAIL",
        provider="INDEED",
        source_account="hr@example.com",
        external_id=f"gmail-{suffix}",
        status="RECEIVED",
        raw_metadata={"gmail_message_id": f"gmail-{suffix}"},
    )
    db.add(event)
    db.flush()
    task = IndeedEmailResumeTask(
        owner_sub=owner_sub,
        ingestion_event_id=event.id,
        candidate_name=f"Candidate {suffix}",
        job_title="Country Manager Chile",
        status=status,
        available_at=available_at,
        lease_token=lease_token,
        lease_expires_at=lease_expires_at,
        attempt_count=attempt_count,
        created_at=created_at or NOW,
        updated_at=created_at or NOW,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def test_claim_returns_oldest_eligible_task_and_hides_active_lease():
    service = _service()
    engine, db = _db()
    try:
        older = _task(db, suffix="old", created_at=NOW - timedelta(minutes=2))
        newer = _task(db, suffix="new", created_at=NOW - timedelta(minutes=1))

        first = service.claim_next_task(db, owner_sub="owner-1", now=NOW)
        second = service.claim_next_task(db, owner_sub="owner-1", now=NOW)

        assert first is not None and first.task_id == older.id
        assert second is not None and second.task_id == newer.id
        assert first.lease_token != second.lease_token
        assert _utc(first.lease_expires_at) == NOW + timedelta(seconds=600)

        db.refresh(older)
        assert older.status == "CLAIMED"
        assert older.attempt_count == 1
    finally:
        db.close()
        engine.dispose()


def test_claim_does_not_return_only_actively_leased_task():
    service = _service()
    engine, db = _db()
    try:
        _task(
            db,
            suffix="active",
            status="CLAIMED",
            lease_token="active-token",
            lease_expires_at=NOW + timedelta(minutes=5),
            attempt_count=1,
        )

        assert service.claim_next_task(db, owner_sub="owner-1", now=NOW) is None
    finally:
        db.close()
        engine.dispose()


def test_expired_claim_is_reclaimable_with_new_token_and_old_token_is_rejected():
    service = _service()
    engine, db = _db()
    try:
        task = _task(
            db,
            suffix="expired",
            status="CLAIMED",
            lease_token="old-token",
            lease_expires_at=NOW - timedelta(seconds=1),
            attempt_count=1,
        )

        claimed = service.claim_next_task(db, owner_sub="owner-1", now=NOW)

        assert claimed is not None
        assert claimed.task_id == task.id
        assert claimed.lease_token != "old-token"
        with pytest.raises(service.ResumeTaskLeaseConflict):
            service.heartbeat(
                db,
                owner_sub="owner-1",
                task_id=task.id,
                lease_token="old-token",
                now=NOW,
            )
        with pytest.raises(service.ResumeTaskLeaseConflict):
            service.record_failure(
                db,
                owner_sub="owner-1",
                task_id=task.id,
                lease_token="old-token",
                code="RESUME_DOWNLOAD_FAILED",
                now=NOW,
            )
    finally:
        db.close()
        engine.dispose()


def test_heartbeat_extends_same_lease_by_600_seconds():
    service = _service()
    engine, db = _db()
    try:
        _task(db, suffix="heartbeat")
        claimed = service.claim_next_task(db, owner_sub="owner-1", now=NOW)
        assert claimed is not None

        extended = service.heartbeat(
            db,
            owner_sub="owner-1",
            task_id=claimed.task_id,
            lease_token=claimed.lease_token,
            now=NOW + timedelta(seconds=120),
        )

        assert _utc(extended) == NOW + timedelta(seconds=720)
        row = db.get(IndeedEmailResumeTask, claimed.task_id)
        assert row is not None
        assert row.lease_token == claimed.lease_token
        assert _utc(row.lease_expires_at) == NOW + timedelta(seconds=720)
    finally:
        db.close()
        engine.dispose()


def test_needs_human_clears_lease_and_requires_explicit_resume():
    service = _service()
    engine, db = _db()
    try:
        _task(db, suffix="human")
        claimed = service.claim_next_task(db, owner_sub="owner-1", now=NOW)
        assert claimed is not None

        service.mark_needs_human(
            db,
            owner_sub="owner-1",
            task_id=claimed.task_id,
            lease_token=claimed.lease_token,
            code="INDEED_LOGIN_REQUIRED",
            now=NOW,
        )
        row = db.get(IndeedEmailResumeTask, claimed.task_id)
        assert row is not None
        assert row.status == "NEEDS_HUMAN"
        assert row.lease_token is None
        assert row.lease_expires_at is None
        assert row.attempt_count == 1
        assert service.claim_next_task(db, owner_sub="owner-1", now=NOW) is None

        service.resume_after_human(
            db,
            owner_sub="owner-1",
            task_id=claimed.task_id,
        )
        resumed = db.get(IndeedEmailResumeTask, claimed.task_id)
        assert resumed is not None
        assert resumed.status == "WAITING_DOWNLOAD"
        assert resumed.attempt_count == 1
        assert resumed.last_error_code is None
        reclaimed = service.claim_next_task(
            db,
            owner_sub="owner-1",
            now=NOW + timedelta(seconds=1),
        )
        assert reclaimed is not None
        assert reclaimed.task_id == claimed.task_id
        assert db.get(IndeedEmailResumeTask, claimed.task_id).attempt_count == 2
    finally:
        db.close()
        engine.dispose()


def test_failure_backoff_first_second_and_third_attempt():
    service = _service()
    engine, db = _db()
    try:
        task = _task(db, suffix="retry")

        first = service.claim_next_task(db, owner_sub="owner-1", now=NOW)
        assert first is not None
        status = service.record_failure(
            db,
            owner_sub="owner-1",
            task_id=task.id,
            lease_token=first.lease_token,
            code="RESUME_DOWNLOAD_FAILED",
            now=NOW,
        )
        row = db.get(IndeedEmailResumeTask, task.id)
        assert status == "RETRY"
        assert row.status == "RETRY"
        assert _utc(row.available_at) == NOW + timedelta(seconds=15)
        assert row.lease_token is None
        assert service.claim_next_task(
            db,
            owner_sub="owner-1",
            now=NOW + timedelta(seconds=14),
        ) is None

        second = service.claim_next_task(
            db,
            owner_sub="owner-1",
            now=NOW + timedelta(seconds=15),
        )
        assert second is not None
        status = service.record_failure(
            db,
            owner_sub="owner-1",
            task_id=task.id,
            lease_token=second.lease_token,
            code="RESUME_DOWNLOAD_FAILED",
            now=NOW + timedelta(seconds=15),
        )
        row = db.get(IndeedEmailResumeTask, task.id)
        assert status == "RETRY"
        assert _utc(row.available_at) == NOW + timedelta(seconds=75)

        third = service.claim_next_task(
            db,
            owner_sub="owner-1",
            now=NOW + timedelta(seconds=75),
        )
        assert third is not None
        status = service.record_failure(
            db,
            owner_sub="owner-1",
            task_id=task.id,
            lease_token=third.lease_token,
            code="RESUME_DOWNLOAD_FAILED",
            now=NOW + timedelta(seconds=75),
        )
        row = db.get(IndeedEmailResumeTask, task.id)
        assert status == "FAILED"
        assert row.status == "FAILED"
        assert row.attempt_count == 3
        assert row.available_at is None
        assert row.lease_token is None
    finally:
        db.close()
        engine.dispose()


def test_owner_isolation_and_stats():
    service = _service()
    engine, db = _db()
    try:
        _task(db, suffix="a-wait", owner_sub="owner-a")
        _task(db, suffix="a-done", owner_sub="owner-a", status="COMPLETED")
        _task(db, suffix="b-wait", owner_sub="owner-b")

        claimed = service.claim_next_task(db, owner_sub="owner-a", now=NOW)
        assert claimed is not None
        assert claimed.candidate_name == "Candidate a-wait"
        stats = service.stats(db, owner_sub="owner-a")
        assert {
            key: stats[key]
            for key in ("pending", "claimed", "completed", "needs_human", "retry", "failed")
        } == {
            "pending": 0,
            "claimed": 1,
            "completed": 1,
            "needs_human": 0,
            "retry": 0,
            "failed": 0,
        }
        assert stats["last_error_code"] is None
        assert stats["last_error_candidate"] is None
        assert stats["last_error_status"] is None
        assert service.stats(db, owner_sub="owner-b")["pending"] == 1
    finally:
        db.close()
        engine.dispose()


def test_restart_keeps_82_completed_terminal_and_reclaims_task_83():
    service = _service()
    engine, db = _db()
    try:
        for index in range(82):
            _task(
                db,
                suffix=f"done-{index:03d}",
                status="COMPLETED",
                created_at=NOW - timedelta(minutes=200 - index),
            )
        pending = _task(
            db,
            suffix="083",
            status="CLAIMED",
            created_at=NOW - timedelta(minutes=1),
            lease_token="crashed-worker-token",
            lease_expires_at=NOW - timedelta(seconds=5),
            attempt_count=1,
        )

        db.close()
        db = Session(engine)
        claimed = service.claim_next_task(db, owner_sub="owner-1", now=NOW)

        assert claimed is not None
        assert claimed.task_id == pending.id
        assert claimed.lease_token != "crashed-worker-token"
        assert (
            db.query(IndeedEmailResumeTask)
            .filter(IndeedEmailResumeTask.status == "COMPLETED")
            .count()
            == 82
        )
    finally:
        db.close()
        engine.dispose()
