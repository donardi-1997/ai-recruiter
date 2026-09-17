"""State machine and document handoff for Indeed email resume-download tasks."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

from sqlalchemy.orm import Session

from app.config import (
    get_gmail_oauth_settings,
    get_gmail_settings,
    get_indeed_resume_agent_settings,
)
from app.domains.candidate_ingestion import gmail_integration, indeed_email_repository, repository
from app.domains.candidate_ingestion.models import (
    CandidateIngestionDocument,
    IndeedEmailResumeTask,
)
from app.infrastructure.gmail_oauth_store import GmailOAuthSecretStore
from app.infrastructure.ingestion.storage import EmailIngestionStorage
from app.integrations.email_ingestion.gmail import GmailClient
from app.integrations.email_ingestion.indeed_email_parser import (
    InvalidIndeedMessage,
    InvalidIndeedResumeLink,
    NotIndeedMessage,
    parse_indeed_application_email,
)

LEASE_SECONDS = 600
MAX_ATTEMPTS = 3
FIRST_RETRY_SECONDS = 15
SECOND_RETRY_SECONDS = 60
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024


class ResumeTaskNotFound(LookupError):
    pass


class ResumeTaskLeaseConflict(RuntimeError):
    pass


class ResumeTaskStateConflict(RuntimeError):
    pass


class ResumeClaimResolutionError(RuntimeError):
    """Public-safe failure while resolving the current Indeed resume URL."""


class ResumeUploadConflict(RuntimeError):
    """Raised when a task already has a different persisted resume document."""


class ResumeUploadValidationError(ValueError):
    def __init__(self, status_code: int, code: str):
        self.status_code = int(status_code)
        self.code = str(code)
        super().__init__(self.code)


@dataclass(frozen=True)
class ClaimedResumeTask:
    task_id: str
    candidate_name: str
    job_title: str
    lease_token: str
    lease_expires_at: datetime


@dataclass(frozen=True)
class ClaimedResumeTaskWithUrl:
    task_id: str
    candidate_name: str
    job_title: str
    resume_url: str
    lease_token: str
    lease_expires_at: datetime


def _now(value: datetime | None) -> datetime:
    return value or datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _owned_task(db: Session, *, owner_sub: str, task_id: str) -> IndeedEmailResumeTask:
    task = indeed_email_repository.get_owned_task(
        db,
        owner_sub=owner_sub,
        task_id=task_id,
    )
    if task is None:
        raise ResumeTaskNotFound("RESUME_TASK_NOT_FOUND")
    return task


def require_active_lease(
    db: Session,
    *,
    owner_sub: str,
    task_id: str,
    lease_token: str,
    now: datetime | None = None,
) -> IndeedEmailResumeTask:
    """Return the owned task only when the caller still holds its active lease."""
    task = _owned_task(db, owner_sub=owner_sub, task_id=task_id)
    supplied = str(lease_token or "")
    stored = str(task.lease_token or "")
    if task.status != "CLAIMED" or not supplied or not stored:
        raise ResumeTaskLeaseConflict("RESUME_TASK_LEASE_INVALID")
    if not hmac.compare_digest(supplied, stored):
        raise ResumeTaskLeaseConflict("RESUME_TASK_LEASE_INVALID")
    expires_at = _as_utc(task.lease_expires_at)
    current = _as_utc(_now(now))
    if expires_at is None or current is None or expires_at < current:
        raise ResumeTaskLeaseConflict("RESUME_TASK_LEASE_EXPIRED")
    return task


def claim_next_task(
    db: Session,
    *,
    owner_sub: str,
    now: datetime | None = None,
) -> ClaimedResumeTask | None:
    current = _now(now)
    task = indeed_email_repository.claim_next_eligible_task(
        db,
        owner_sub=owner_sub,
        now=current,
        lease_seconds=LEASE_SECONDS,
    )
    if task is None:
        return None
    return ClaimedResumeTask(
        task_id=task.id,
        candidate_name=task.candidate_name,
        job_title=task.job_title,
        lease_token=str(task.lease_token),
        lease_expires_at=task.lease_expires_at,
    )


def _gmail_client_from_oauth():
    """Build a Gmail transport from the existing OAuth secret without exposing it."""
    current = get_gmail_settings()
    oauth = get_gmail_oauth_settings()
    store = GmailOAuthSecretStore(oauth.secret_id)
    payload = gmail_integration._read_oauth_secret(oauth, store)
    resolved = gmail_integration._resolved_gmail_settings(current, payload)
    if not resolved.configured:
        raise RuntimeError("GMAIL_NOT_CONFIGURED")
    return GmailClient(resolved)


def _safe_resolution_failure(
    db: Session,
    *,
    owner_sub: str,
    task_id: str,
    lease_token: str,
    code: str,
    human_required: bool,
) -> None:
    if human_required:
        task = _owned_task(db, owner_sub=owner_sub, task_id=task_id)
        event = repository.get_event(
            db,
            task.ingestion_event_id,
            owner_sub=owner_sub,
        )
        if event is not None:
            event.status = "NEEDS_REVIEW"
            event.last_error_code = code
            event.last_error_message = "El enlace del CV de Indeed requiere revision manual."
            db.commit()
        mark_needs_human(
            db,
            owner_sub=owner_sub,
            task_id=task_id,
            lease_token=lease_token,
            code=code,
        )
    else:
        record_failure(
            db,
            owner_sub=owner_sub,
            task_id=task_id,
            lease_token=lease_token,
            code=code,
        )


def claim_next_task_with_resume_url(
    db: Session,
    *,
    owner_sub: str,
    mailbox_client=None,
) -> ClaimedResumeTaskWithUrl | None:
    """Lease one task and resolve its current Indeed URL only for this response."""
    claimed = claim_next_task(db, owner_sub=owner_sub)
    if claimed is None:
        return None

    task = _owned_task(db, owner_sub=owner_sub, task_id=claimed.task_id)
    event = repository.get_event(
        db,
        task.ingestion_event_id,
        owner_sub=owner_sub,
    )
    metadata = dict(event.raw_metadata or {}) if event is not None else {}
    message_id = str(metadata.get("gmail_message_id") or "").strip()
    if event is None or not message_id:
        _safe_resolution_failure(
            db,
            owner_sub=owner_sub,
            task_id=claimed.task_id,
            lease_token=claimed.lease_token,
            code="GMAIL_MESSAGE_ID_MISSING",
            human_required=False,
        )
        raise ResumeClaimResolutionError("Gmail message is unavailable.")

    client = mailbox_client
    try:
        if client is None:
            client = _gmail_client_from_oauth()
        raw_message = client.get_message(message_id)
        parser_settings = get_indeed_resume_agent_settings()
        parsed = parse_indeed_application_email(
            raw_message,
            sender_domains=parser_settings.sender_domains,
            resume_host_suffixes=parser_settings.resume_host_suffixes,
        )
    except (InvalidIndeedResumeLink, InvalidIndeedMessage, NotIndeedMessage) as exc:
        code = (
            "INDEED_RESUME_LINK_INVALID"
            if isinstance(exc, InvalidIndeedResumeLink)
            else "INDEED_EMAIL_INVALID"
        )
        _safe_resolution_failure(
            db,
            owner_sub=owner_sub,
            task_id=claimed.task_id,
            lease_token=claimed.lease_token,
            code=code,
            human_required=True,
        )
        raise ResumeClaimResolutionError("Indeed resume link requires review.") from exc
    except Exception as exc:
        _safe_resolution_failure(
            db,
            owner_sub=owner_sub,
            task_id=claimed.task_id,
            lease_token=claimed.lease_token,
            code="GMAIL_MESSAGE_UNAVAILABLE",
            human_required=False,
        )
        raise ResumeClaimResolutionError("Gmail message is unavailable.") from exc

    return ClaimedResumeTaskWithUrl(
        task_id=claimed.task_id,
        candidate_name=claimed.candidate_name,
        job_title=claimed.job_title,
        resume_url=parsed.resume_url,
        lease_token=claimed.lease_token,
        lease_expires_at=claimed.lease_expires_at,
    )


def heartbeat(
    db: Session,
    *,
    owner_sub: str,
    task_id: str,
    lease_token: str,
    now: datetime | None = None,
) -> datetime:
    current = _now(now)
    task = require_active_lease(
        db,
        owner_sub=owner_sub,
        task_id=task_id,
        lease_token=lease_token,
        now=current,
    )
    task.lease_expires_at = current + timedelta(seconds=LEASE_SECONDS)
    db.commit()
    db.refresh(task)
    return task.lease_expires_at


def _clear_lease(task: IndeedEmailResumeTask) -> None:
    task.lease_token = None
    task.lease_expires_at = None
    task.claimed_at = None


def mark_needs_human(
    db: Session,
    *,
    owner_sub: str,
    task_id: str,
    lease_token: str,
    code: str,
    now: datetime | None = None,
) -> None:
    task = require_active_lease(
        db,
        owner_sub=owner_sub,
        task_id=task_id,
        lease_token=lease_token,
        now=now,
    )
    task.status = "NEEDS_HUMAN"
    task.available_at = None
    task.last_error_code = str(code or "INDEED_HUMAN_REQUIRED")[:120]
    task.last_error_message = "Indeed requiere intervencion manual para continuar."
    _clear_lease(task)
    db.commit()


def resume_after_human(
    db: Session,
    *,
    owner_sub: str,
    task_id: str,
) -> None:
    task = _owned_task(db, owner_sub=owner_sub, task_id=task_id)
    if task.status != "NEEDS_HUMAN":
        raise ResumeTaskStateConflict("RESUME_TASK_NOT_WAITING_FOR_HUMAN")
    task.status = "WAITING_DOWNLOAD"
    task.available_at = None
    task.last_error_code = None
    task.last_error_message = None
    _clear_lease(task)
    db.commit()


def record_failure(
    db: Session,
    *,
    owner_sub: str,
    task_id: str,
    lease_token: str,
    code: str,
    now: datetime | None = None,
) -> str:
    current = _now(now)
    task = require_active_lease(
        db,
        owner_sub=owner_sub,
        task_id=task_id,
        lease_token=lease_token,
        now=current,
    )
    task.last_error_code = str(code or "RESUME_DOWNLOAD_FAILED")[:120]
    task.last_error_message = "No fue posible descargar el CV de Indeed."
    _clear_lease(task)

    attempt = int(task.attempt_count or 0)
    if attempt >= MAX_ATTEMPTS:
        task.status = "FAILED"
        task.available_at = None
        task.completed_at = current
    else:
        task.status = "RETRY"
        delay = FIRST_RETRY_SECONDS if attempt <= 1 else SECOND_RETRY_SECONDS
        task.available_at = current + timedelta(seconds=delay)
        task.completed_at = None

    db.commit()
    return task.status


def _safe_pdf_filename(filename: str | None) -> str:
    raw = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    stem = PurePosixPath(raw).stem.strip() if raw else "indeed-resume"
    stem = stem or "indeed-resume"
    safe = "".join(ch if ch.isalnum() or ch in " ._-" else "_" for ch in stem).strip()
    return f"{safe or 'indeed-resume'}.pdf"


def store_resume_pdf(
    db: Session,
    *,
    owner_sub: str,
    task_id: str,
    lease_token: str,
    filename: str | None,
    content_type: str,
    data: bytes,
    storage=None,
    now: datetime | None = None,
) -> CandidateIngestionDocument:
    """Validate and persist a downloaded PDF exactly once for the leased task."""
    payload = bytes(data or b"")
    if str(content_type or "").strip().casefold() != "application/pdf":
        raise ResumeUploadValidationError(422, "RESUME_CONTENT_TYPE_INVALID")
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise ResumeUploadValidationError(413, "RESUME_TOO_LARGE")
    if not payload.startswith(b"%PDF-"):
        raise ResumeUploadValidationError(422, "RESUME_NOT_PDF")

    digest = hashlib.sha256(payload).hexdigest()
    task = _owned_task(db, owner_sub=owner_sub, task_id=task_id)
    event = repository.get_event(
        db,
        task.ingestion_event_id,
        owner_sub=owner_sub,
    )
    if event is None:
        raise ResumeTaskNotFound("RESUME_EVENT_NOT_FOUND")

    existing_documents = repository.list_documents(db, event_id=event.id)
    if existing_documents:
        if (
            len(existing_documents) == 1
            and existing_documents[0].document_sha256 == digest
            and task.status == "COMPLETED"
        ):
            return existing_documents[0]
        raise ResumeUploadConflict("RESUME_DOCUMENT_CONFLICT")

    task = require_active_lease(
        db,
        owner_sub=owner_sub,
        task_id=task_id,
        lease_token=lease_token,
        now=now,
    )

    safe_filename = _safe_pdf_filename(filename)
    source_storage = storage or EmailIngestionStorage()
    source_key = source_storage.store_source_document(
        event_id=event.id,
        attachment_id=f"indeed-agent-{task.id}",
        filename=safe_filename,
        data=payload,
        content_type="application/pdf",
    )
    document = repository.create_document(
        db,
        ingestion_event_id=event.id,
        filename=safe_filename,
        content_type="application/pdf",
        size_bytes=len(payload),
        source_s3_key=source_key,
        document_sha256=digest,
        status="STORED",
    )

    current = _now(now)
    event.status = "STORED"
    event.last_error_code = None
    event.last_error_message = None
    event.queue_dispatched_at = None
    task.status = "COMPLETED"
    task.available_at = None
    task.last_error_code = None
    task.last_error_message = None
    task.completed_at = current
    _clear_lease(task)
    db.commit()
    db.refresh(document)
    return document


def stats(db: Session, *, owner_sub: str) -> dict[str, int]:
    counts = indeed_email_repository.count_by_status(db, owner_sub=owner_sub)
    return {
        "pending": counts.get("WAITING_DOWNLOAD", 0),
        "claimed": counts.get("CLAIMED", 0),
        "completed": counts.get("COMPLETED", 0),
        "needs_human": counts.get("NEEDS_HUMAN", 0),
        "retry": counts.get("RETRY", 0),
        "failed": counts.get("FAILED", 0),
    }
