"""State machine for leased Indeed email resume-download tasks."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.domains.candidate_ingestion import indeed_email_repository
from app.domains.candidate_ingestion.models import IndeedEmailResumeTask

LEASE_SECONDS = 600
MAX_ATTEMPTS = 3
FIRST_RETRY_SECONDS = 15
SECOND_RETRY_SECONDS = 60


class ResumeTaskNotFound(LookupError):
    pass


class ResumeTaskLeaseConflict(RuntimeError):
    pass


class ResumeTaskStateConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class ClaimedResumeTask:
    task_id: str
    candidate_name: str
    job_title: str
    lease_token: str
    lease_expires_at: datetime


def _now(value: datetime | None) -> datetime:
    return value or datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _owned_task(db: Session, *, owner_sub: str, task_id: str) -> IndeedEmailResumeTask:
    task = indeed_email_repository.get_owned_task(
        db,
        owner_sub=owner_sub,
        task_id=task_id,
    )
    if task is None:
        raise ResumeTaskNotFound("RESUME_TASK_NOT_FOUND")
    return task


def require_active_lease(
    db: Session,
    *,
    owner_sub: str,
    task_id: str,
    lease_token: str,
    now: datetime | None = None,
) -> IndeedEmailResumeTask:
    """Return the owned task only when the caller still holds its active lease."""
    task = _owned_task(db, owner_sub=owner_sub, task_id=task_id)
    supplied = str(lease_token or "")
    stored = str(task.lease_token or "")
    if task.status != "CLAIMED" or not supplied or not stored:
        raise ResumeTaskLeaseConflict("RESUME_TASK_LEASE_INVALID")
    if not hmac.compare_digest(supplied, stored):
        raise ResumeTaskLeaseConflict("RESUME_TASK_LEASE_INVALID")
    expires_at = _as_utc(task.lease_expires_at)
    current = _as_utc(_now(now))
    if expires_at is None or current is None or expires_at < current:
        raise ResumeTaskLeaseConflict("RESUME_TASK_LEASE_EXPIRED")
    return task


def claim_next_task(
    db: Session,
    *,
    owner_sub: str,
    now: datetime | None = None,
) -> ClaimedResumeTask | None:
    current = _now(now)
    task = indeed_email_repository.claim_next_eligible_task(
        db,
        owner_sub=owner_sub,
        now=current,
        lease_seconds=LEASE_SECONDS,
    )
    if task is None:
        return None
    return ClaimedResumeTask(
        task_id=task.id,
        candidate_name=task.candidate_name,
        job_title=task.job_title,
        lease_token=str(task.lease_token),
        lease_expires_at=task.lease_expires_at,
    )


def heartbeat(
    db: Session,
    *,
    owner_sub: str,
    task_id: str,
    lease_token: str,
    now: datetime | None = None,
) -> datetime:
    current = _now(now)
    task = require_active_lease(
        db,
        owner_sub=owner_sub,
        task_id=task_id,
        lease_token=lease_token,
        now=current,
    )
    task.lease_expires_at = current + timedelta(seconds=LEASE_SECONDS)
    db.commit()
    db.refresh(task)
    return task.lease_expires_at


def _clear_lease(task: IndeedEmailResumeTask) -> None:
    task.lease_token = None
    task.lease_expires_at = None
    task.claimed_at = None


def mark_needs_human(
    db: Session,
    *,
    owner_sub: str,
    task_id: str,
    lease_token: str,
    code: str,
    now: datetime | None = None,
) -> None:
    task = require_active_lease(
        db,
        owner_sub=owner_sub,
        task_id=task_id,
        lease_token=lease_token,
        now=now,
    )
    task.status = "NEEDS_HUMAN"
    task.available_at = None
    task.last_error_code = str(code or "INDEED_HUMAN_REQUIRED")[:120]
    task.last_error_message = "Indeed requiere intervencion manual para continuar."
    _clear_lease(task)
    db.commit()


def resume_after_human(
    db: Session,
    *,
    owner_sub: str,
    task_id: str,
) -> None:
    task = _owned_task(db, owner_sub=owner_sub, task_id=task_id)
    if task.status != "NEEDS_HUMAN":
        raise ResumeTaskStateConflict("RESUME_TASK_NOT_WAITING_FOR_HUMAN")
    task.status = "WAITING_DOWNLOAD"
    task.available_at = None
    task.last_error_code = None
    task.last_error_message = None
    _clear_lease(task)
    db.commit()


def record_failure(
    db: Session,
    *,
    owner_sub: str,
    task_id: str,
    lease_token: str,
    code: str,
    now: datetime | None = None,
) -> str:
    current = _now(now)
    task = require_active_lease(
        db,
        owner_sub=owner_sub,
        task_id=task_id,
        lease_token=lease_token,
        now=current,
    )
    task.last_error_code = str(code or "RESUME_DOWNLOAD_FAILED")[:120]
    task.last_error_message = "No fue posible descargar el CV de Indeed."
    _clear_lease(task)

    attempt = int(task.attempt_count or 0)
    if attempt >= MAX_ATTEMPTS:
        task.status = "FAILED"
        task.available_at = None
        task.completed_at = current
    else:
        task.status = "RETRY"
        delay = FIRST_RETRY_SECONDS if attempt <= 1 else SECOND_RETRY_SECONDS
        task.available_at = current + timedelta(seconds=delay)
        task.completed_at = None

    db.commit()
    return task.status


def stats(db: Session, *, owner_sub: str) -> dict[str, int]:
    counts = indeed_email_repository.count_by_status(db, owner_sub=owner_sub)
    return {
        "pending": counts.get("WAITING_DOWNLOAD", 0),
        "claimed": counts.get("CLAIMED", 0),
        "completed": counts.get("COMPLETED", 0),
        "needs_human": counts.get("NEEDS_HUMAN", 0),
        "retry": counts.get("RETRY", 0),
        "failed": counts.get("FAILED", 0),
    }
