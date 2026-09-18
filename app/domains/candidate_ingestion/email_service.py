"""Application service for durable Gmail -> Candidate Ingestion Core handoff."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domains.candidate_ingestion import repository
from app.domains.candidate_ingestion.indeed_email_service import discover_indeed_email
from app.domains.candidate_ingestion.models import CandidateIngestionEvent
from app.integrations.email_ingestion.parser import (
    EmailSenderNotAllowed,
    parse_gmail_message,
)
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




def _assert_sender_allowed(
    raw_message: dict[str, Any],
    *,
    allowed_senders: tuple[str, ...],
    allowed_sender_domains: tuple[str, ...],
) -> None:
    normalized_senders = {
        str(value or "").strip().casefold()
        for value in allowed_senders
        if str(value or "").strip()
    }
    normalized_domains = tuple(
        str(value or "").strip().casefold().lstrip(".")
        for value in allowed_sender_domains
        if str(value or "").strip()
    )
    if not normalized_senders and not normalized_domains:
        return

    payload = raw_message.get("payload") or {}
    from_value = ""
    for item in payload.get("headers") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip().casefold() == "from":
            from_value = str(item.get("value") or "").strip()
            break

    _display_name, sender_address = parseaddr(from_value)
    sender = sender_address.strip().casefold()
    sender_domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
    if not sender_domain:
        raise EmailSenderNotAllowed("EMAIL_SENDER_NOT_ALLOWED")

    if normalized_senders and sender not in normalized_senders:
        raise EmailSenderNotAllowed("EMAIL_SENDER_NOT_ALLOWED")

    if normalized_domains and not any(
        sender_domain == domain or sender_domain.endswith("." + domain)
        for domain in normalized_domains
    ):
        raise EmailSenderNotAllowed("EMAIL_SENDER_NOT_ALLOWED")


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
    allowed_sender_domains: tuple[str, ...] = (),
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
        if normalized_provider == "INDEED":
            has_task = existing.indeed_email_resume_task is not None
            has_documents = bool(repository.list_documents(db, event_id=existing.id))
            if not has_task and not has_documents:
                raw_message = mailbox_client.get_message(message_id)
                _assert_sender_allowed(
                    raw_message,
                    allowed_senders=allowed_senders,
                    allowed_sender_domains=allowed_sender_domains,
                )
                discovered = discover_indeed_email(
                    db,
                    owner_sub=owner_sub,
                    source_account=normalized_source_account,
                    raw_message=raw_message,
                )
                if discovered is not None:
                    return EmailIngestionResult(
                        event=_refresh_event(db, discovered.event),
                        created=False,
                    )
        return EmailIngestionResult(event=_refresh_event(db, existing), created=False)

    raw_message = mailbox_client.get_message(message_id)
    _assert_sender_allowed(
        raw_message,
        allowed_senders=allowed_senders,
        allowed_sender_domains=allowed_sender_domains,
    )

    if normalized_provider == "INDEED":
        discovered = discover_indeed_email(
            db,
            owner_sub=owner_sub,
            source_account=normalized_source_account,
            raw_message=raw_message,
        )
        if discovered is not None:
            return EmailIngestionResult(
                event=_refresh_event(db, discovered.event),
                created=discovered.created,
            )

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
