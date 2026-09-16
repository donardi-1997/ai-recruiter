"""Persistence helpers for the provider-neutral candidate ingestion core."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.candidate_ingestion.models import (
    CandidateIngestionDocument,
    CandidateIngestionEvent,
)


def get_event_by_external_id(
    db: Session,
    *,
    owner_sub: str,
    source: str,
    provider: str,
    external_id: str,
) -> CandidateIngestionEvent | None:
    return (
        db.query(CandidateIngestionEvent)
        .filter(
            CandidateIngestionEvent.owner_sub == owner_sub,
            CandidateIngestionEvent.source == source,
            CandidateIngestionEvent.provider == provider,
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
    external_id: str,
    status: str,
    raw_metadata: dict,
) -> CandidateIngestionEvent:
    event = CandidateIngestionEvent(
        owner_sub=owner_sub,
        source=source,
        provider=provider,
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
