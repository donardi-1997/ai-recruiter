"""State machine and document handoff for Indeed email resume-download tasks."""

from __future__ import annotations

import hashlib
import hmac
import io
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

from sqlalchemy.orm import Session

from app.config import (
    get_gmail_oauth_settings,
    get_gmail_settings,
    get_indeed_resume_agent_settings,
)
from app.domains.candidate_ingestion import (
    gmail_integration,
    indeed_email_repository,
    job_resolution,
    repository,
)
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
PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


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

    # Reconciliation tasks are allowed to start from the stable Indeed candidates
    # workspace. The browser driver will deterministically locate the exact
    # candidate by name + job title and never requires a persisted provider URL.
    if event is not None and metadata.get("resume_agent_lookup_only") is True:
        return ClaimedResumeTaskWithUrl(
            task_id=claimed.task_id,
            candidate_name=claimed.candidate_name,
            job_title=claimed.job_title,
            resume_url="https://employers.indeed.com/candidates",
            lease_token=claimed.lease_token,
            lease_expires_at=claimed.lease_expires_at,
        )

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
        code = str(exc or "").strip() or (
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

    metadata.update(
        {
            "candidate_name": parsed.candidate_name,
            "job_title": parsed.job_title,
            "external_job_id": parsed.external_job_id,
            "sender": parsed.sender,
            "subject": parsed.subject,
        }
    )
    try:
        job = job_resolution.resolve_or_create_indeed_job(
            db,
            owner_sub=owner_sub,
            metadata=metadata,
        )
        event.raw_metadata = metadata
        event.job_id = job.id if job is not None else None
        task.job_id = job.id if job is not None else None
        task.candidate_name = parsed.candidate_name
        task.job_title = parsed.job_title
        db.commit()
    except Exception as exc:
        db.rollback()
        _safe_resolution_failure(
            db,
            owner_sub=owner_sub,
            task_id=claimed.task_id,
            lease_token=claimed.lease_token,
            code="INDEED_JOB_RESOLUTION_FAILED",
            human_required=False,
        )
        raise ResumeClaimResolutionError("Indeed job resolution failed.") from exc

    return ClaimedResumeTaskWithUrl(
        task_id=claimed.task_id,
        candidate_name=parsed.candidate_name,
        job_title=parsed.job_title,
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


def _is_docx(payload: bytes) -> bool:
    if not payload.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError):
        return False
    return "[Content_Types].xml" in names and "word/document.xml" in names


def _validate_resume_document(
    *,
    filename: str | None,
    content_type: str,
    data: bytes,
) -> str:
    payload = bytes(data or b"")
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise ResumeUploadValidationError(413, "RESUME_TOO_LARGE")

    declared = str(content_type or "").split(";", 1)[0].strip().casefold()
    suffix = PurePosixPath(
        str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    ).suffix.casefold()

    if payload.startswith(b"%PDF-"):
        if declared not in {PDF_CONTENT_TYPE, "application/octet-stream", ""}:
            raise ResumeUploadValidationError(422, "RESUME_CONTENT_TYPE_INVALID")
        return PDF_CONTENT_TYPE

    if _is_docx(payload):
        if declared not in {DOCX_CONTENT_TYPE, "application/octet-stream", ""}:
            raise ResumeUploadValidationError(422, "RESUME_CONTENT_TYPE_INVALID")
        return DOCX_CONTENT_TYPE

    if declared == PDF_CONTENT_TYPE or suffix == ".pdf":
        raise ResumeUploadValidationError(422, "RESUME_NOT_PDF")
    if declared == DOCX_CONTENT_TYPE or suffix == ".docx":
        raise ResumeUploadValidationError(422, "RESUME_NOT_DOCX")
    raise ResumeUploadValidationError(422, "RESUME_UNSUPPORTED_FORMAT")


def _safe_resume_filename(filename: str | None, *, content_type: str) -> str:
    raw = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    stem = PurePosixPath(raw).stem.strip() if raw else "indeed-resume"
    stem = stem or "indeed-resume"
    safe = "".join(ch if ch.isalnum() or ch in " ._-" else "_" for ch in stem).strip()
    extension = ".docx" if content_type == DOCX_CONTENT_TYPE else ".pdf"
    return f"{safe or 'indeed-resume'}{extension}"


def store_resume_document(
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
    """Validate and persist a supported resume exactly once for the leased task."""
    payload = bytes(data or b"")
    canonical_content_type = _validate_resume_document(
        filename=filename,
        content_type=content_type,
        data=payload,
    )
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

    safe_filename = _safe_resume_filename(
        filename,
        content_type=canonical_content_type,
    )
    source_storage = storage or EmailIngestionStorage()
    source_key = source_storage.store_source_document(
        event_id=event.id,
        attachment_id=f"indeed-agent-{task.id}",
        filename=safe_filename,
        data=payload,
        content_type=canonical_content_type,
    )
    document = repository.create_document(
        db,
        ingestion_event_id=event.id,
        filename=safe_filename,
        content_type=canonical_content_type,
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
    """Backward-compatible alias for the former PDF-only service contract."""
    return store_resume_document(
        db,
        owner_sub=owner_sub,
        task_id=task_id,
        lease_token=lease_token,
        filename=filename,
        content_type=content_type,
        data=data,
        storage=storage,
        now=now,
    )


def get_active_smoke_task(
    db: Session,
    *,
    owner_sub: str,
) -> dict:
    """Return the current owner-scoped smoke-test task without mutating it."""
    active_statuses = ("WAITING_DOWNLOAD", "RETRY", "NEEDS_HUMAN", "CLAIMED")
    task = (
        db.query(IndeedEmailResumeTask)
        .filter(
            IndeedEmailResumeTask.owner_sub == owner_sub,
            IndeedEmailResumeTask.status.in_(active_statuses),
        )
        .order_by(
            IndeedEmailResumeTask.created_at.asc(),
            IndeedEmailResumeTask.id.asc(),
        )
        .first()
    )
    if task is None:
        task = (
            db.query(IndeedEmailResumeTask)
            .filter(
                IndeedEmailResumeTask.owner_sub == owner_sub,
                IndeedEmailResumeTask.status == "FAILED",
            )
            .order_by(
                IndeedEmailResumeTask.created_at.asc(),
                IndeedEmailResumeTask.id.asc(),
            )
            .first()
        )
    if task is None:
        return {
            "task_id": None,
            "status": None,
            "candidate_name": None,
            "job_title": None,
            "last_error_code": None,
        }
    return {
        "task_id": str(task.id),
        "status": str(task.status),
        "candidate_name": task.candidate_name,
        "job_title": task.job_title,
        "last_error_code": task.last_error_code,
    }


def reactivate_one_archived_task(
    db: Session,
    *,
    owner_sub: str,
) -> dict:
    """Prepare exactly one archived historical task for a controlled smoke test."""
    active_statuses = ("WAITING_DOWNLOAD", "RETRY", "NEEDS_HUMAN", "CLAIMED")
    active = (
        db.query(IndeedEmailResumeTask)
        .filter(
            IndeedEmailResumeTask.owner_sub == owner_sub,
            IndeedEmailResumeTask.status.in_(active_statuses),
        )
        .order_by(
            IndeedEmailResumeTask.created_at.asc(),
            IndeedEmailResumeTask.id.asc(),
        )
        .first()
    )
    if active is None:
        active = (
            db.query(IndeedEmailResumeTask)
            .filter(
                IndeedEmailResumeTask.owner_sub == owner_sub,
                IndeedEmailResumeTask.status == "FAILED",
            )
            .order_by(
                IndeedEmailResumeTask.created_at.asc(),
                IndeedEmailResumeTask.id.asc(),
            )
            .first()
        )
    if active is not None:
        return {
            "reactivated": False,
            "task_id": str(active.id),
            "status": str(active.status),
            "candidate_name": active.candidate_name,
            "job_title": active.job_title,
            "last_error_code": active.last_error_code,
        }

    task = (
        db.query(IndeedEmailResumeTask)
        .filter(
            IndeedEmailResumeTask.owner_sub == owner_sub,
            IndeedEmailResumeTask.status == "IGNORED",
            IndeedEmailResumeTask.last_error_code == "HISTORICAL_BOOTSTRAP_SKIPPED",
        )
        .order_by(
            IndeedEmailResumeTask.created_at.desc(),
            IndeedEmailResumeTask.id.desc(),
        )
        .first()
    )
    if task is None:
        return {
            "reactivated": False,
            "task_id": None,
            "status": None,
            "candidate_name": None,
            "job_title": None,
            "last_error_code": None,
        }

    task.status = "WAITING_DOWNLOAD"
    task.available_at = None
    task.lease_token = None
    task.lease_expires_at = None
    task.claimed_at = None
    task.attempt_count = 0
    task.last_error_code = None
    task.last_error_message = None
    db.commit()
    db.refresh(task)
    return {
        "reactivated": True,
        "task_id": str(task.id),
        "status": str(task.status),
        "candidate_name": task.candidate_name,
        "job_title": task.job_title,
        "last_error_code": None,
    }


def retry_active_needs_human_task(
    db: Session,
    *,
    owner_sub: str,
) -> dict:
    """Retry the current owner-scoped smoke-test task in place.

    NEEDS_HUMAN, RETRY, and terminal FAILED tasks are eligible. FAILED retries
    reset the attempt budget so the diagnostic build can observe the real UI.
    """
    retryable_statuses = ("NEEDS_HUMAN", "RETRY", "FAILED")
    task = (
        db.query(IndeedEmailResumeTask)
        .filter(
            IndeedEmailResumeTask.owner_sub == owner_sub,
            IndeedEmailResumeTask.status.in_(retryable_statuses),
        )
        .order_by(
            IndeedEmailResumeTask.created_at.asc(),
            IndeedEmailResumeTask.id.asc(),
        )
        .first()
    )
    if task is None:
        return {
            "retried": False,
            "task_id": None,
            "status": None,
            "candidate_name": None,
            "job_title": None,
        }

    task.status = "WAITING_DOWNLOAD"
    task.available_at = None
    task.attempt_count = 0
    task.completed_at = None
    task.last_error_code = None
    task.last_error_message = None
    _clear_lease(task)
    db.commit()
    db.refresh(task)
    return {
        "retried": True,
        "task_id": str(task.id),
        "status": str(task.status),
        "candidate_name": task.candidate_name,
        "job_title": task.job_title,
    }


def requeue_failed_tasks(
    db: Session,
    *,
    owner_sub: str,
) -> int:
    """Move only this owner's terminal FAILED tasks back to a clean download state."""
    tasks = (
        db.query(IndeedEmailResumeTask)
        .filter(
            IndeedEmailResumeTask.owner_sub == owner_sub,
            IndeedEmailResumeTask.status == "FAILED",
        )
        .all()
    )
    for task in tasks:
        task.status = "WAITING_DOWNLOAD"
        task.available_at = None
        task.attempt_count = 0
        task.last_error_code = None
        task.last_error_message = None
        task.completed_at = None
        _clear_lease(task)
    if tasks:
        db.commit()
    return len(tasks)


def requeue_needs_human_tasks(
    db: Session,
    *,
    owner_sub: str,
) -> int:
    """Move only this owner's NEEDS_HUMAN tasks back to WAITING_DOWNLOAD."""
    tasks = (
        db.query(IndeedEmailResumeTask)
        .filter(
            IndeedEmailResumeTask.owner_sub == owner_sub,
            IndeedEmailResumeTask.status == "NEEDS_HUMAN",
        )
        .all()
    )
    for task in tasks:
        task.status = "WAITING_DOWNLOAD"
        task.available_at = None
        task.last_error_code = None
        task.last_error_message = None
        _clear_lease(task)
    if tasks:
        db.commit()
    return len(tasks)


def stats(db: Session, *, owner_sub: str) -> dict[str, object]:
    counts = indeed_email_repository.count_by_status(db, owner_sub=owner_sub)
    latest_error = (
        db.query(IndeedEmailResumeTask)
        .filter(
            IndeedEmailResumeTask.owner_sub == owner_sub,
            IndeedEmailResumeTask.last_error_code.is_not(None),
        )
        .order_by(
            IndeedEmailResumeTask.updated_at.desc(),
            IndeedEmailResumeTask.id.desc(),
        )
        .first()
    )
    return {
        "pending": counts.get("WAITING_DOWNLOAD", 0),
        "claimed": counts.get("CLAIMED", 0),
        "completed": counts.get("COMPLETED", 0),
        "needs_human": counts.get("NEEDS_HUMAN", 0),
        "retry": counts.get("RETRY", 0),
        "failed": counts.get("FAILED", 0),
        "last_error_code": (
            str(latest_error.last_error_code)
            if latest_error is not None and latest_error.last_error_code
            else None
        ),
        "last_error_candidate": (
            str(latest_error.candidate_name)
            if latest_error is not None and latest_error.candidate_name
            else None
        ),
        "last_error_status": (
            str(latest_error.status)
            if latest_error is not None and latest_error.status
            else None
        ),
    }
