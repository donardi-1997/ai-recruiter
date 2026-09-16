"""Durable vacancy reevaluation task scheduling."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import JobReevaluationTask


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
        # Another request can race to schedule the same job/version. The unique
        # constraint is the final authority; return the winner instead of
        # surfacing a duplicate scheduling error.
        existing = get_reevaluation_task(
            db,
            job_id=job.id,
            target_evaluation_version=target_version,
        )
        if existing is None:
            raise
        return existing
