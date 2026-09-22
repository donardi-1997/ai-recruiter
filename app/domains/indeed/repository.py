"""Persistence helpers for Indeed integration state."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import (
    IndeedCandidateLink,
    IndeedCandidateSyncState,
    IndeedConnection,
    IndeedDispositionEvent,
    IndeedJobLink,
    IndeedSyncEvent,
)


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


def get_job_link_by_sourced_posting(
    db: Session,
    *,
    owner_sub: str,
    sourced_posting_id: str,
) -> IndeedJobLink | None:
    return (
        db.query(IndeedJobLink)
        .filter(
            IndeedJobLink.owner_sub == owner_sub,
            IndeedJobLink.sourced_posting_id == sourced_posting_id,
        )
        .first()
    )


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


# Candidate Sync persistence deliberately avoids committing inside helpers so
# a fetched batch can be processed atomically before its acknowledgment token
# is advanced.

def get_or_create_candidate_sync_state(db: Session, owner_sub: str) -> IndeedCandidateSyncState:
    state = (
        db.query(IndeedCandidateSyncState)
        .filter(IndeedCandidateSyncState.owner_sub == owner_sub)
        .first()
    )
    if state is None:
        state = IndeedCandidateSyncState(owner_sub=owner_sub)
        db.add(state)
        db.flush()
    return state


def get_candidate_link_by_asset(
    db: Session,
    *,
    owner_sub: str,
    asset_id: str,
) -> IndeedCandidateLink | None:
    return (
        db.query(IndeedCandidateLink)
        .filter(
            IndeedCandidateLink.owner_sub == owner_sub,
            IndeedCandidateLink.asset_id == asset_id,
        )
        .first()
    )


def get_candidate_link(
    db: Session,
    *,
    owner_sub: str,
    job_id: str,
    candidate_id: str,
) -> IndeedCandidateLink | None:
    return (
        db.query(IndeedCandidateLink)
        .filter(
            IndeedCandidateLink.owner_sub == owner_sub,
            IndeedCandidateLink.job_id == job_id,
            IndeedCandidateLink.candidate_id == candidate_id,
        )
        .order_by(
            IndeedCandidateLink.staged_at.desc().nullslast(),
            IndeedCandidateLink.created_at.desc(),
            IndeedCandidateLink.id.desc(),
        )
        .first()
    )


def create_candidate_link(
    db: Session,
    *,
    owner_sub: str,
    candidate_id: str,
    job_id: str,
    asset_id: str,
    registration_id: str | None = None,
    employer_identifier: str | None = None,
    source_enum_key: str | None = None,
    source_name: str | None = None,
    sourced_posting_id: str | None = None,
    indeed_apply_id: str | None = None,
    ittk: str | None = None,
    universal_apply_id: str | None = None,
    resume_name: str | None = None,
    resume_url: str | None = None,
    staged_test: bool = False,
    staged_at: datetime | None = None,
) -> IndeedCandidateLink:
    existing = get_candidate_link_by_asset(db, owner_sub=owner_sub, asset_id=asset_id)
    if existing is not None:
        return existing
    link = IndeedCandidateLink(
        owner_sub=owner_sub,
        candidate_id=candidate_id,
        job_id=job_id,
        asset_id=asset_id,
        registration_id=registration_id,
        employer_identifier=employer_identifier,
        source_enum_key=source_enum_key,
        source_name=source_name,
        sourced_posting_id=sourced_posting_id,
        indeed_apply_id=indeed_apply_id,
        ittk=ittk,
        universal_apply_id=universal_apply_id,
        resume_name=resume_name,
        resume_url=resume_url,
        staged_test=bool(staged_test),
        staged_at=staged_at,
    )
    db.add(link)
    db.flush()
    return link


def mark_unacknowledged_links_acknowledged(db: Session, *, owner_sub: str, acknowledged_at: datetime) -> int:
    return (
        db.query(IndeedCandidateLink)
        .filter(
            IndeedCandidateLink.owner_sub == owner_sub,
            IndeedCandidateLink.acknowledged_at.is_(None),
        )
        .update(
            {IndeedCandidateLink.acknowledged_at: acknowledged_at},
            synchronize_session=False,
        )
    )


def queue_disposition_event(
    db: Session,
    *,
    owner_sub: str,
    candidate_link_id: str,
    local_status: str,
    indeed_status: str,
    status_changed_at: datetime,
) -> IndeedDispositionEvent:
    existing = (
        db.query(IndeedDispositionEvent)
        .filter(
            IndeedDispositionEvent.candidate_link_id == candidate_link_id,
            IndeedDispositionEvent.local_status == local_status,
            IndeedDispositionEvent.status_changed_at == status_changed_at,
        )
        .first()
    )
    if existing is not None:
        return existing
    event = IndeedDispositionEvent(
        owner_sub=owner_sub,
        candidate_link_id=candidate_link_id,
        local_status=local_status,
        indeed_status=indeed_status,
        status_changed_at=status_changed_at,
        sync_status="PENDING",
    )
    db.add(event)
    db.flush()
    return event


def list_disposition_events_for_sync(
    db: Session,
    *,
    owner_sub: str,
    limit: int = 25,
) -> list[IndeedDispositionEvent]:
    bounded_limit = min(max(int(limit), 1), 25)
    return (
        db.query(IndeedDispositionEvent)
        .filter(
            IndeedDispositionEvent.owner_sub == owner_sub,
            IndeedDispositionEvent.sync_status.in_(("PENDING", "FAILED")),
            IndeedDispositionEvent.attempt_count < 5,
        )
        .order_by(
            IndeedDispositionEvent.status_changed_at.asc(),
            IndeedDispositionEvent.created_at.asc(),
            IndeedDispositionEvent.id.asc(),
        )
        .limit(bounded_limit)
        .all()
    )


def mark_disposition_attempted(events: list[IndeedDispositionEvent]) -> None:
    for event in events:
        event.attempt_count += 1


def mark_disposition_sent(event: IndeedDispositionEvent, *, sent_at: datetime) -> None:
    event.sync_status = "SENT"
    event.sent_at = sent_at
    event.last_error = None


def mark_disposition_failed(event: IndeedDispositionEvent, *, error: str) -> None:
    event.sync_status = "FAILED"
    event.last_error = error[:2000]
