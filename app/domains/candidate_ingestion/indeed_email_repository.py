"""Persistence helpers for the leased Indeed email resume queue."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.domains.candidate_ingestion.models import IndeedEmailResumeTask

LEASE_SECONDS = 600


def _eligible(now: datetime):
    return or_(
        IndeedEmailResumeTask.status == "WAITING_DOWNLOAD",
        and_(
            IndeedEmailResumeTask.status == "RETRY",
            or_(
                IndeedEmailResumeTask.available_at.is_(None),
                IndeedEmailResumeTask.available_at <= now,
            ),
        ),
        and_(
            IndeedEmailResumeTask.status == "CLAIMED",
            IndeedEmailResumeTask.lease_expires_at.is_not(None),
            IndeedEmailResumeTask.lease_expires_at < now,
        ),
    )


def get_owned_task(
    db: Session,
    *,
    owner_sub: str,
    task_id: str,
) -> IndeedEmailResumeTask | None:
    return (
        db.query(IndeedEmailResumeTask)
        .filter(
            IndeedEmailResumeTask.id == task_id,
            IndeedEmailResumeTask.owner_sub == owner_sub,
        )
        .one_or_none()
    )


def claim_next_eligible_task(
    db: Session,
    *,
    owner_sub: str,
    now: datetime,
    lease_seconds: int = LEASE_SECONDS,
) -> IndeedEmailResumeTask | None:
    """Claim the oldest eligible task, using SKIP LOCKED on PostgreSQL."""
    query = (
        db.query(IndeedEmailResumeTask)
        .filter(
            IndeedEmailResumeTask.owner_sub == owner_sub,
            _eligible(now),
        )
        .order_by(
            IndeedEmailResumeTask.created_at.asc(),
            IndeedEmailResumeTask.id.asc(),
        )
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)

    task = query.first()
    if task is None:
        return None

    task.status = "CLAIMED"
    task.lease_token = secrets.token_urlsafe(32)
    task.lease_expires_at = now + timedelta(seconds=max(1, int(lease_seconds)))
    task.claimed_at = now
    task.available_at = None
    task.attempt_count = int(task.attempt_count or 0) + 1
    task.last_error_code = None
    task.last_error_message = None
    db.commit()
    db.refresh(task)
    return task


def count_by_status(db: Session, *, owner_sub: str) -> dict[str, int]:
    rows = (
        db.query(IndeedEmailResumeTask.status)
        .filter(IndeedEmailResumeTask.owner_sub == owner_sub)
        .all()
    )
    counts: dict[str, int] = {}
    for (status,) in rows:
        key = str(status or "")
        counts[key] = counts.get(key, 0) + 1
    return counts