"""Persistence helpers for the provider-neutral candidate ingestion core."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.domains.candidate_ingestion.models import (
    CandidateIngestionCursor,
    CandidateIngestionDocument,
    CandidateIngestionEvent,
)


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
