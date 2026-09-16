"""Persistence helpers for durable Indeed resume-processing work."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.domains.indeed.resume_models import IndeedResumeIngestion

TERMINAL_RESUME_STATUSES = {"COMPLETED", "FAILED"}


def get_or_create_resume_ingestion(
    db: Session,
    *,
    owner_sub: str,
    candidate_link_id: str,
) -> IndeedResumeIngestion:
    ingestion = (
        db.query(IndeedResumeIngestion)
        .filter(
            IndeedResumeIngestion.owner_sub == owner_sub,
            IndeedResumeIngestion.candidate_link_id == candidate_link_id,
        )
        .first()
    )
    if ingestion is None:
        ingestion = IndeedResumeIngestion(
            owner_sub=owner_sub,
            candidate_link_id=candidate_link_id,
            status="PENDING",
        )
        db.add(ingestion)
        db.flush()
    return ingestion


def get_resume_ingestion(
    db: Session,
    ingestion_id: str,
    *,
    owner_sub: str | None = None,
) -> IndeedResumeIngestion | None:
    query = db.query(IndeedResumeIngestion).filter(IndeedResumeIngestion.id == ingestion_id)
    if owner_sub is not None:
        query = query.filter(IndeedResumeIngestion.owner_sub == owner_sub)
    return query.first()


def get_resume_ingestion_for_candidate_link(
    db: Session,
    *,
    owner_sub: str,
    candidate_link_id: str,
) -> IndeedResumeIngestion | None:
    return (
        db.query(IndeedResumeIngestion)
        .filter(
            IndeedResumeIngestion.owner_sub == owner_sub,
            IndeedResumeIngestion.candidate_link_id == candidate_link_id,
        )
        .first()
    )


def list_undispatched_resume_ingestions(
    db: Session,
    *,
    owner_sub: str | None = None,
    limit: int = 100,
) -> list[IndeedResumeIngestion]:
    query = db.query(IndeedResumeIngestion).filter(
        IndeedResumeIngestion.status == "PENDING",
        IndeedResumeIngestion.queue_dispatched_at.is_(None),
    )
    if owner_sub is not None:
        query = query.filter(IndeedResumeIngestion.owner_sub == owner_sub)
    return (
        query.order_by(
            IndeedResumeIngestion.created_at.asc(),
            IndeedResumeIngestion.id.asc(),
        )
        .limit(max(1, min(int(limit), 1000)))
        .all()
    )


def claim_resume_ingestion(
    db: Session,
    *,
    ingestion_id: str,
    token: str,
    now: datetime | None = None,
    lease_seconds: int = 300,
) -> bool:
    now = now or datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=max(1, int(lease_seconds)))
    updated = (
        db.query(IndeedResumeIngestion)
        .filter(
            IndeedResumeIngestion.id == ingestion_id,
            ~IndeedResumeIngestion.status.in_(TERMINAL_RESUME_STATUSES),
            or_(
                IndeedResumeIngestion.processing_token.is_(None),
                IndeedResumeIngestion.heartbeat_at.is_(None),
                IndeedResumeIngestion.heartbeat_at < stale_before,
            ),
        )
        .update(
            {
                IndeedResumeIngestion.processing_token: token,
                IndeedResumeIngestion.heartbeat_at: now,
                IndeedResumeIngestion.attempt_count: IndeedResumeIngestion.attempt_count + 1,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return bool(updated)


def heartbeat_resume_ingestion(
    db: Session,
    *,
    ingestion_id: str,
    token: str,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(timezone.utc)
    updated = (
        db.query(IndeedResumeIngestion)
        .filter(
            IndeedResumeIngestion.id == ingestion_id,
            IndeedResumeIngestion.processing_token == token,
            ~IndeedResumeIngestion.status.in_(TERMINAL_RESUME_STATUSES),
        )
        .update(
            {IndeedResumeIngestion.heartbeat_at: now},
            synchronize_session=False,
        )
    )
    db.commit()
    return bool(updated)


def release_resume_ingestion(
    db: Session,
    *,
    ingestion_id: str,
    token: str,
) -> bool:
    updated = (
        db.query(IndeedResumeIngestion)
        .filter(
            IndeedResumeIngestion.id == ingestion_id,
            IndeedResumeIngestion.processing_token == token,
        )
        .update(
            {
                IndeedResumeIngestion.processing_token: None,
                IndeedResumeIngestion.heartbeat_at: None,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return bool(updated)
