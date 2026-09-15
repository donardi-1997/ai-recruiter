"""Persistence helpers for Indeed integration state."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import IndeedConnection, IndeedJobLink, IndeedSyncEvent


def get_or_create_connection(db: Session, owner_sub: str, employer_id: str = "") -> IndeedConnection:
    connection = db.query(IndeedConnection).filter(IndeedConnection.owner_sub == owner_sub).first()
    if connection is None:
        connection = IndeedConnection(owner_sub=owner_sub, employer_id=employer_id or None, status="CONFIGURED")
        db.add(connection)
    else:
        connection.employer_id = employer_id or connection.employer_id
        connection.status = "CONFIGURED"
        connection.last_error = None
    db.commit()
    db.refresh(connection)
    return connection


def get_job_link(db: Session, job_id: str, owner_sub: str) -> IndeedJobLink | None:
    return db.query(IndeedJobLink).filter(IndeedJobLink.job_id == job_id, IndeedJobLink.owner_sub == owner_sub).first()


def upsert_job_link(db: Session, *, job_id: str, owner_sub: str, sourced_posting_id: str, employer_job_id: str) -> IndeedJobLink:
    link = get_job_link(db, job_id, owner_sub)
    if link is None:
        link = IndeedJobLink(job_id=job_id, owner_sub=owner_sub)
        db.add(link)
    link.sourced_posting_id = sourced_posting_id
    link.employer_job_id = employer_job_id
    link.last_error = None
    link.last_synced_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(link)
    return link


def update_status(db: Session, link: IndeedJobLink, status: dict) -> IndeedJobLink:
    link.external_status = status
    link.last_synced_at = datetime.now(timezone.utc)
    link.last_error = None
    db.commit()
    db.refresh(link)
    return link


def start_event(db: Session, *, owner_sub: str, job_id: str, operation: str) -> IndeedSyncEvent:
    event = IndeedSyncEvent(owner_sub=owner_sub, job_id=job_id, operation=operation, status="PENDING")
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def finish_event(db: Session, event: IndeedSyncEvent, *, external_id: str | None = None) -> None:
    event.status = "SUCCEEDED"
    event.external_id = external_id
    event.completed_at = datetime.now(timezone.utc)
    db.commit()


def fail_event(db: Session, event: IndeedSyncEvent, exc: Exception) -> None:
    event.status = "FAILED"
    event.error_code = getattr(exc, "code", exc.__class__.__name__)
    event.error_message = str(exc)[:2000]
    event.completed_at = datetime.now(timezone.utc)
    db.commit()
