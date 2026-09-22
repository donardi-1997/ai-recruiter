"""Discover Indeed application notifications without persisting provider resume URLs."""

from __future__ import annotations

from dataclasses import dataclass
from email.utils import parseaddr
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domains.candidate_ingestion import job_resolution, repository
from app.domains.candidate_ingestion.models import (
    CandidateIngestionEvent,
    IndeedEmailResumeTask,
)
from app.integrations.email_ingestion.indeed_email_parser import (
    InvalidIndeedMessage,
    InvalidIndeedResumeLink,
    NotIndeedMessage,
    ParsedIndeedApplication,
    parse_indeed_application_email,
)


@dataclass(frozen=True)
class IndeedEmailDiscoveryResult:
    event: CandidateIngestionEvent
    task: IndeedEmailResumeTask | None
    created: bool


def _normalize_source_account(value: str) -> str:
    return str(value or "").strip().casefold()


def _headers(raw_message: dict[str, Any]) -> dict[str, str]:
    payload = raw_message.get("payload") or {}
    values: dict[str, str] = {}
    for item in payload.get("headers") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().casefold()
        if name and name not in values:
            values[name] = str(item.get("value") or "").strip()
    return values


def _safe_raw_metadata(
    raw_message: dict[str, Any],
    *,
    source_account: str,
    parsed: ParsedIndeedApplication | None = None,
) -> dict[str, Any]:
    headers = _headers(raw_message)
    _display_name, sender_address = parseaddr(headers.get("from", ""))
    message_id = str(raw_message.get("id") or "").strip()
    thread_id = str(raw_message.get("threadId") or "").strip() or None
    history_id = str(raw_message.get("historyId") or "").strip() or None
    internal_date_raw = str(raw_message.get("internalDate") or "").strip()
    try:
        internal_date_ms = int(internal_date_raw) if internal_date_raw else None
    except ValueError:
        internal_date_ms = None

    metadata: dict[str, Any] = {
        "gmail_message_id": message_id,
        "gmail_thread_id": thread_id,
        "gmail_history_id": history_id,
        "source_account": source_account,
        "sender": sender_address.strip().casefold(),
        "subject": headers.get("subject", ""),
        "internal_date_ms": internal_date_ms,
    }
    if parsed is not None:
        metadata["sender"] = parsed.sender
        metadata["subject"] = parsed.subject
        metadata["candidate_name"] = parsed.candidate_name
        metadata["job_title"] = parsed.job_title
        metadata["external_job_id"] = parsed.external_job_id
    return metadata


def _get_task(
    db: Session,
    *,
    event_id: str,
) -> IndeedEmailResumeTask | None:
    return (
        db.query(IndeedEmailResumeTask)
        .filter(IndeedEmailResumeTask.ingestion_event_id == event_id)
        .one_or_none()
    )


def _refresh_result(
    db: Session,
    event: CandidateIngestionEvent,
    *,
    created: bool,
) -> IndeedEmailDiscoveryResult:
    db.refresh(event)
    return IndeedEmailDiscoveryResult(
        event=event,
        task=_get_task(db, event_id=event.id),
        created=created,
    )


def _existing_result(
    db: Session,
    *,
    owner_sub: str,
    source_account: str,
    message_id: str,
) -> IndeedEmailDiscoveryResult | None:
    event = repository.get_event_by_external_id(
        db,
        owner_sub=owner_sub,
        source="EMAIL",
        provider="INDEED",
        source_account=source_account,
        external_id=message_id,
    )
    if event is None:
        return None
    return _refresh_result(db, event, created=False)


def _mark_job_not_synced(
    db: Session,
    *,
    event: CandidateIngestionEvent,
    metadata: dict[str, Any],
) -> None:
    """Keep an application durable without creating browser work before its job exists."""
    event.status = "NEEDS_REVIEW"
    event.raw_metadata = metadata
    event.job_id = None
    event.last_error_code = "INDEED_JOB_NOT_SYNCED_YET"
    event.last_error_message = (
        "La vacante de Indeed debe sincronizarse antes de procesar esta postulacion."
    )
    db.commit()


def _backfill_existing_event(
    db: Session,
    *,
    owner_sub: str,
    source_account: str,
    raw_message: dict[str, Any],
    event: CandidateIngestionEvent,
) -> IndeedEmailDiscoveryResult:
    """Repair or advance an existing Gmail event once its vacancy becomes available."""
    existing_task = _get_task(db, event_id=event.id)
    if existing_task is not None or repository.list_documents(db, event_id=event.id):
        return _refresh_result(db, event, created=False)

    try:
        parsed = parse_indeed_application_email(raw_message)
    except NotIndeedMessage:
        return _refresh_result(db, event, created=False)
    except InvalidIndeedResumeLink:
        event.status = "NEEDS_REVIEW"
        event.raw_metadata = _safe_raw_metadata(
            raw_message,
            source_account=source_account,
        )
        event.last_error_code = "INDEED_RESUME_LINK_INVALID"
        event.last_error_message = "El enlace del CV de Indeed no es valido."
        db.commit()
        return _refresh_result(db, event, created=False)
    except InvalidIndeedMessage:
        event.status = "NEEDS_REVIEW"
        event.raw_metadata = _safe_raw_metadata(
            raw_message,
            source_account=source_account,
        )
        event.last_error_code = "INDEED_EMAIL_INVALID"
        event.last_error_message = "El correo de Indeed no contiene una postulacion utilizable."
        db.commit()
        return _refresh_result(db, event, created=False)

    metadata = _safe_raw_metadata(
        raw_message,
        source_account=source_account,
        parsed=parsed,
    )
    job = job_resolution.resolve_or_create_indeed_job(
        db,
        owner_sub=owner_sub,
        metadata=metadata,
    )
    if job is None:
        _mark_job_not_synced(db, event=event, metadata=metadata)
        return _refresh_result(db, event, created=False)

    try:
        event.status = "RECEIVED"
        event.raw_metadata = metadata
        event.job_id = job.id
        event.last_error_code = "RESUME_DOWNLOAD_PENDING"
        event.last_error_message = "El CV de Indeed esta pendiente de descarga."
        db.add(
            IndeedEmailResumeTask(
                owner_sub=owner_sub,
                ingestion_event_id=event.id,
                job_id=job.id,
                candidate_name=parsed.candidate_name,
                job_title=parsed.job_title,
                status="WAITING_DOWNLOAD",
            )
        )
        db.commit()
        return _refresh_result(db, event, created=False)
    except IntegrityError:
        db.rollback()
        winner = _existing_result(
            db,
            owner_sub=owner_sub,
            source_account=source_account,
            message_id=parsed.message_id,
        )
        if winner is None:
            raise
        return winner


def _persist_review_event(
    db: Session,
    *,
    owner_sub: str,
    source_account: str,
    raw_message: dict[str, Any],
    error_code: str,
    error_message: str,
) -> IndeedEmailDiscoveryResult:
    message_id = str(raw_message.get("id") or "").strip()
    if not message_id:
        raise InvalidIndeedMessage("GMAIL_MESSAGE_ID_MISSING")

    existing = _existing_result(
        db,
        owner_sub=owner_sub,
        source_account=source_account,
        message_id=message_id,
    )
    if existing is not None:
        return existing

    try:
        event = repository.create_event(
            db,
            owner_sub=owner_sub,
            source="EMAIL",
            provider="INDEED",
            source_account=source_account,
            external_id=message_id,
            status="NEEDS_REVIEW",
            raw_metadata=_safe_raw_metadata(
                raw_message,
                source_account=source_account,
            ),
        )
        event.last_error_code = error_code
        event.last_error_message = error_message
        db.commit()
        return _refresh_result(db, event, created=True)
    except IntegrityError:
        db.rollback()
        winner = _existing_result(
            db,
            owner_sub=owner_sub,
            source_account=source_account,
            message_id=message_id,
        )
        if winner is None:
            raise
        return winner


def discover_indeed_email(
    db: Session,
    *,
    owner_sub: str,
    source_account: str,
    raw_message: dict,
) -> IndeedEmailDiscoveryResult | None:
    """Discover one trusted Indeed application without allowing Gmail to create jobs."""
    normalized_source_account = _normalize_source_account(source_account)
    message_id = str(raw_message.get("id") or "").strip()
    if message_id:
        existing = _existing_result(
            db,
            owner_sub=owner_sub,
            source_account=normalized_source_account,
            message_id=message_id,
        )
        if existing is not None:
            return _backfill_existing_event(
                db,
                owner_sub=owner_sub,
                source_account=normalized_source_account,
                raw_message=raw_message,
                event=existing.event,
            )

    try:
        parsed = parse_indeed_application_email(raw_message)
    except NotIndeedMessage:
        return None
    except InvalidIndeedResumeLink:
        return _persist_review_event(
            db,
            owner_sub=owner_sub,
            source_account=normalized_source_account,
            raw_message=raw_message,
            error_code="INDEED_RESUME_LINK_INVALID",
            error_message="El enlace del CV de Indeed no es valido.",
        )
    except InvalidIndeedMessage:
        return _persist_review_event(
            db,
            owner_sub=owner_sub,
            source_account=normalized_source_account,
            raw_message=raw_message,
            error_code="INDEED_EMAIL_INVALID",
            error_message="El correo de Indeed no contiene una postulacion utilizable.",
        )

    metadata = _safe_raw_metadata(
        raw_message,
        source_account=normalized_source_account,
        parsed=parsed,
    )
    job = job_resolution.resolve_or_create_indeed_job(
        db,
        owner_sub=owner_sub,
        metadata=metadata,
    )

    try:
        event = repository.create_event(
            db,
            owner_sub=owner_sub,
            source="EMAIL",
            provider="INDEED",
            source_account=normalized_source_account,
            external_id=parsed.message_id,
            status="RECEIVED" if job is not None else "NEEDS_REVIEW",
            raw_metadata=metadata,
        )
        event.job_id = job.id if job is not None else None
        if job is None:
            event.last_error_code = "INDEED_JOB_NOT_SYNCED_YET"
            event.last_error_message = (
                "La vacante de Indeed debe sincronizarse antes de procesar esta postulacion."
            )
            db.commit()
            return _refresh_result(db, event, created=True)

        event.last_error_code = "RESUME_DOWNLOAD_PENDING"
        event.last_error_message = "El CV de Indeed esta pendiente de descarga."
        db.flush()

        task = IndeedEmailResumeTask(
            owner_sub=owner_sub,
            ingestion_event_id=event.id,
            job_id=job.id,
            candidate_name=parsed.candidate_name,
            job_title=parsed.job_title,
            status="WAITING_DOWNLOAD",
        )
        db.add(task)
        db.commit()
        return _refresh_result(db, event, created=True)
    except IntegrityError:
        db.rollback()
        winner = _existing_result(
            db,
            owner_sub=owner_sub,
            source_account=normalized_source_account,
            message_id=parsed.message_id,
        )
        if winner is None:
            raise
        return winner
