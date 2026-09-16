"""Application service for durable Gmail -> Candidate Ingestion Core handoff."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domains.candidate_ingestion import repository
from app.domains.candidate_ingestion.models import CandidateIngestionEvent
from app.integrations.email_ingestion.parser import parse_gmail_message
from app.infrastructure.ingestion.storage import EmailIngestionStorage

MAX_DOCUMENT_BYTES = 15 * 1024 * 1024


@dataclass(frozen=True)
class EmailIngestionResult:
    event: CandidateIngestionEvent
    created: bool


def _metadata(parsed, *, source_account: str) -> dict[str, Any]:
    return {
        "gmail_message_id": parsed.message_id,
        "gmail_thread_id": parsed.thread_id,
        "gmail_history_id": parsed.history_id,
        "provider_message_id": parsed.provider_message_id,
        "source_account": source_account,
        "sender": parsed.sender,
        "subject": parsed.subject,
        "internal_date_ms": parsed.internal_date_ms,
        "attachment_count": len(parsed.attachments),
    }


def _refresh_event(db: Session, event: CandidateIngestionEvent) -> CandidateIngestionEvent:
    db.refresh(event)
    _ = event.documents
    return event


def ingest_gmail_message(
    db: Session,
    *,
    owner_sub: str,
    message_id: str,
    mailbox_client,
    provider: str,
    source_account: str = "",
    allowed_senders: tuple[str, ...] = (),
    storage=None,
) -> EmailIngestionResult:
    """Persist one Gmail message and supported resume attachments idempotently."""
    normalized_provider = str(provider or "").strip().upper()
    normalized_source_account = str(source_account or "").strip().casefold()
    if not normalized_provider:
        raise ValueError("INGESTION_PROVIDER_REQUIRED")

    existing = repository.get_event_by_external_id(
        db,
        owner_sub=owner_sub,
        source="EMAIL",
        provider=normalized_provider,
        source_account=normalized_source_account,
        external_id=message_id,
    )
    if existing is not None:
        return EmailIngestionResult(event=_refresh_event(db, existing), created=False)

    raw_message = mailbox_client.get_message(message_id)
    parsed = parse_gmail_message(
        raw_message,
        allowed_senders=allowed_senders,
    )

    try:
        event = repository.create_event(
            db,
            owner_sub=owner_sub,
            source="EMAIL",
            provider=normalized_provider,
            source_account=normalized_source_account,
            external_id=parsed.message_id,
            status="RECEIVED",
            raw_metadata=_metadata(parsed, source_account=normalized_source_account),
        )
        db.commit()
        db.refresh(event)
    except IntegrityError:
        db.rollback()
        winner = repository.get_event_by_external_id(
            db,
            owner_sub=owner_sub,
            source="EMAIL",
            provider=normalized_provider,
            source_account=normalized_source_account,
            external_id=parsed.message_id,
        )
        if winner is None:
            raise
        return EmailIngestionResult(event=_refresh_event(db, winner), created=False)

    if not parsed.attachments:
        event.status = "NEEDS_REVIEW"
        event.last_error_code = "RESUME_ATTACHMENT_MISSING"
        event.last_error_message = "No supported PDF or DOCX resume attachment was found."
        db.commit()
        return EmailIngestionResult(event=_refresh_event(db, event), created=True)

    source_storage = storage or EmailIngestionStorage()
    try:
        for attachment in parsed.attachments:
            data = mailbox_client.get_attachment(
                parsed.message_id,
                attachment.attachment_id,
            )
            if not data:
                raise ValueError("EMAIL_ATTACHMENT_EMPTY")
            if len(data) > MAX_DOCUMENT_BYTES:
                raise ValueError("EMAIL_ATTACHMENT_TOO_LARGE")

            document_sha256 = hashlib.sha256(data).hexdigest()
            source_key = source_storage.store_source_document(
                event_id=event.id,
                attachment_id=attachment.attachment_id,
                filename=attachment.filename,
                data=data,
                content_type=attachment.content_type,
            )
            repository.create_document(
                db,
                ingestion_event_id=event.id,
                filename=attachment.filename,
                content_type=attachment.content_type,
                size_bytes=len(data),
                source_s3_key=source_key,
                document_sha256=document_sha256,
                status="STORED",
            )

        event.status = "STORED"
        event.last_error_code = None
        event.last_error_message = None
        db.commit()
        return EmailIngestionResult(event=_refresh_event(db, event), created=True)
    except Exception:
        db.rollback()
        persisted = repository.get_event_by_external_id(
            db,
            owner_sub=owner_sub,
            source="EMAIL",
            provider=normalized_provider,
            source_account=normalized_source_account,
            external_id=parsed.message_id,
        )
        if persisted is not None:
            persisted.status = "RECEIVED"
            persisted.last_error_code = "EMAIL_ATTACHMENT_INGESTION_FAILED"
            persisted.last_error_message = "Candidate email attachment could not be stored."
            db.commit()
        raise
