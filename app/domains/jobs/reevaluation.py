"""Durable vacancy reevaluation task scheduling and lease management."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import JobReevaluationTask

TERMINAL_REEVALUATION_STATUSES = {"COMPLETED", "FAILED"}


def get_reevaluation_task(
    db: Session,
    *,
    job_id: str,
    target_evaluation_version: int,
) -> JobReevaluationTask | None:
    return (
        db.query(JobReevaluationTask)
        .filter(
            JobReevaluationTask.job_id == job_id,
            JobReevaluationTask.target_evaluation_version == int(target_evaluation_version),
        )
        .first()
    )


def get_reevaluation_task_by_id(
    db: Session,
    task_id: str,
    *,
    owner_sub: str | None = None,
) -> JobReevaluationTask | None:
    query = db.query(JobReevaluationTask).filter(JobReevaluationTask.id == task_id)
    if owner_sub is not None:
        query = query.filter(JobReevaluationTask.owner_sub == owner_sub)
    return query.first()


def list_undispatched_reevaluation_tasks(
    db: Session,
    *,
    owner_sub: str | None = None,
    limit: int = 100,
) -> list[JobReevaluationTask]:
    query = db.query(JobReevaluationTask).filter(
        JobReevaluationTask.status == "PENDING",
        JobReevaluationTask.queue_dispatched_at.is_(None),
    )
    if owner_sub is not None:
        query = query.filter(JobReevaluationTask.owner_sub == owner_sub)
    return (
        query.order_by(
            JobReevaluationTask.created_at.asc(),
            JobReevaluationTask.id.asc(),
        )
        .limit(max(1, min(int(limit), 1000)))
        .all()
    )


def claim_reevaluation_task(
    db: Session,
    *,
    task_id: str,
    token: str,
    now: datetime | None = None,
    lease_seconds: int = 300,
) -> bool:
    now = now or datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=max(1, int(lease_seconds)))
    updated = (
        db.query(JobReevaluationTask)
        .filter(
            JobReevaluationTask.id == task_id,
            ~JobReevaluationTask.status.in_(TERMINAL_REEVALUATION_STATUSES),
            or_(
                JobReevaluationTask.processing_token.is_(None),
                JobReevaluationTask.heartbeat_at.is_(None),
                JobReevaluationTask.heartbeat_at < stale_before,
            ),
        )
        .update(
            {
                JobReevaluationTask.processing_token: token,
                JobReevaluationTask.heartbeat_at: now,
                JobReevaluationTask.attempt_count: JobReevaluationTask.attempt_count + 1,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return bool(updated)


def heartbeat_reevaluation_task(
    db: Session,
    *,
    task_id: str,
    token: str,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(timezone.utc)
    updated = (
        db.query(JobReevaluationTask)
        .filter(
            JobReevaluationTask.id == task_id,
            JobReevaluationTask.processing_token == token,
            ~JobReevaluationTask.status.in_(TERMINAL_REEVALUATION_STATUSES),
        )
        .update(
            {JobReevaluationTask.heartbeat_at: now},
            synchronize_session=False,
        )
    )
    db.commit()
    return bool(updated)


def release_reevaluation_task(
    db: Session,
    *,
    task_id: str,
    token: str,
) -> bool:
    updated = (
        db.query(JobReevaluationTask)
        .filter(
            JobReevaluationTask.id == task_id,
            JobReevaluationTask.processing_token == token,
        )
        .update(
            {
                JobReevaluationTask.processing_token: None,
                JobReevaluationTask.heartbeat_at: None,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return bool(updated)


def schedule_reevaluation(
    db: Session,
    *,
    job,
    owner_sub: str,
) -> JobReevaluationTask:
    """Create or return the single durable task for a job evaluation version."""
    target_version = int(getattr(job, "evaluation_version", 1) or 1)
    existing = get_reevaluation_task(
        db,
        job_id=job.id,
        target_evaluation_version=target_version,
    )
    if existing is not None:
        return existing

    task = JobReevaluationTask(
        owner_sub=owner_sub,
        job_id=job.id,
        target_evaluation_version=target_version,
        status="PENDING",
    )
    try:
        with db.begin_nested():
            db.add(task)
            db.flush()
        return task
    except IntegrityError:
        existing = get_reevaluation_task(
            db,
            job_id=job.id,
            target_evaluation_version=target_version,
        )
        if existing is None:
            raise
        return existing
