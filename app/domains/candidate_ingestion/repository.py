"""Persistence helpers for the provider-neutral candidate ingestion core."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.domains.candidate_ingestion.models import (
    CandidateIngestionCursor,
    CandidateIngestionDocument,
    CandidateIngestionEvent,
)

TERMINAL_INGESTION_STATUSES = {"COMPLETED", "FAILED", "NEEDS_REVIEW"}


def get_event_by_external_id(
    db: Session,
    *,
    owner_sub: str,
    source: str,
    provider: str,
    source_account: str,
    external_id: str,
) -> CandidateIngestionEvent | None:
    return (
        db.query(CandidateIngestionEvent)
        .filter(
            CandidateIngestionEvent.owner_sub == owner_sub,
            CandidateIngestionEvent.source == source,
            CandidateIngestionEvent.provider == provider,
            CandidateIngestionEvent.source_account == source_account,
            CandidateIngestionEvent.external_id == external_id,
        )
        .one_or_none()
    )


def get_event(
    db: Session,
    event_id: str,
    *,
    owner_sub: str | None = None,
) -> CandidateIngestionEvent | None:
    query = db.query(CandidateIngestionEvent).filter(
        CandidateIngestionEvent.id == event_id
    )
    if owner_sub is not None:
        query = query.filter(CandidateIngestionEvent.owner_sub == owner_sub)
    return query.one_or_none()


def create_event(
    db: Session,
    *,
    owner_sub: str,
    source: str,
    provider: str,
    source_account: str,
    external_id: str,
    status: str,
    raw_metadata: dict,
) -> CandidateIngestionEvent:
    event = CandidateIngestionEvent(
        owner_sub=owner_sub,
        source=source,
        provider=provider,
        source_account=source_account,
        external_id=external_id,
        status=status,
        raw_metadata=raw_metadata,
    )
    db.add(event)
    db.flush()
    return event


def create_document(
    db: Session,
    *,
    ingestion_event_id: str,
    filename: str,
    content_type: str,
    size_bytes: int,
    source_s3_key: str,
    document_sha256: str,
    status: str = "STORED",
) -> CandidateIngestionDocument:
    document = CandidateIngestionDocument(
        ingestion_event_id=ingestion_event_id,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        source_s3_key=source_s3_key,
        document_sha256=document_sha256,
        status=status,
    )
    db.add(document)
    db.flush()
    return document


def list_documents(
    db: Session,
    *,
    event_id: str,
) -> list[CandidateIngestionDocument]:
    return (
        db.query(CandidateIngestionDocument)
        .filter(CandidateIngestionDocument.ingestion_event_id == event_id)
        .order_by(
            CandidateIngestionDocument.created_at.asc(),
            CandidateIngestionDocument.id.asc(),
        )
        .all()
    )


def list_undispatched_events(
    db: Session,
    *,
    limit: int = 100,
) -> list[CandidateIngestionEvent]:
    return (
        db.query(CandidateIngestionEvent)
        .filter(
            CandidateIngestionEvent.status == "STORED",
            CandidateIngestionEvent.queue_dispatched_at.is_(None),
        )
        .order_by(
            CandidateIngestionEvent.created_at.asc(),
            CandidateIngestionEvent.id.asc(),
        )
        .limit(max(1, min(int(limit), 1000)))
        .all()
    )


def claim_event(
    db: Session,
    *,
    event_id: str,
    token: str,
    now: datetime | None = None,
    lease_seconds: int = 300,
) -> bool:
    now = now or datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=max(1, int(lease_seconds)))
    updated = (
        db.query(CandidateIngestionEvent)
        .filter(
            CandidateIngestionEvent.id == event_id,
            ~CandidateIngestionEvent.status.in_(TERMINAL_INGESTION_STATUSES),
            or_(
                CandidateIngestionEvent.processing_token.is_(None),
                CandidateIngestionEvent.heartbeat_at.is_(None),
                CandidateIngestionEvent.heartbeat_at < stale_before,
            ),
        )
        .update(
            {
                CandidateIngestionEvent.processing_token: token,
                CandidateIngestionEvent.heartbeat_at: now,
                CandidateIngestionEvent.attempt_count: CandidateIngestionEvent.attempt_count
                + 1,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return bool(updated)


def release_event(
    db: Session,
    *,
    event_id: str,
    token: str,
) -> bool:
    updated = (
        db.query(CandidateIngestionEvent)
        .filter(
            CandidateIngestionEvent.id == event_id,
            CandidateIngestionEvent.processing_token == token,
        )
        .update(
            {
                CandidateIngestionEvent.processing_token: None,
                CandidateIngestionEvent.heartbeat_at: None,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return bool(updated)


def get_cursor(
    db: Session,
    *,
    owner_sub: str,
    source: str,
    provider: str,
    source_account: str,
) -> CandidateIngestionCursor | None:
    return (
        db.query(CandidateIngestionCursor)
        .filter(
            CandidateIngestionCursor.owner_sub == owner_sub,
            CandidateIngestionCursor.source == source,
            CandidateIngestionCursor.provider == provider,
            CandidateIngestionCursor.source_account == source_account,
        )
        .one_or_none()
    )


def upsert_cursor(
    db: Session,
    *,
    owner_sub: str,
    source: str,
    provider: str,
    source_account: str,
    cursor_value: str,
) -> CandidateIngestionCursor:
    cursor = get_cursor(
        db,
        owner_sub=owner_sub,
        source=source,
        provider=provider,
        source_account=source_account,
    )
    if cursor is None:
        cursor = CandidateIngestionCursor(
            owner_sub=owner_sub,
            source=source,
            provider=provider,
            source_account=source_account,
        )
        db.add(cursor)
    cursor.cursor_value = str(cursor_value)
    cursor.last_synced_at = datetime.now(timezone.utc)
    db.flush()
    return cursor
