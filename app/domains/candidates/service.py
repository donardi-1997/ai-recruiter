"""Application services for candidate use cases."""

import os

from sqlalchemy.orm import Session

from app.domains.candidates import repository as candidates_repository
from app.domains.candidates.exceptions import (
    CandidateNotFound,
    CandidateRetentionProtected,
    InvalidApplicationStatus,
    JobCandidateNotFound,
    JobNotFound,
)
from app.domains.evaluations import repository as evaluations_repository
from app.domains.jobs import repository as jobs_repository
from app.infrastructure.imports.documents import (
    MAX_DOCUMENT_BYTES,
    DocumentImportError,
    PDF_CONTENT_TYPE,
    extract_document,
)
from app.infrastructure.imports.storage import create_canonical_candidate_download
from app.infrastructure.storage.candidate_documents import index_candidate_document


class LegacyCandidateUploadError(ValueError):
    """Safe validation error for the compatibility bulk-upload endpoint."""


APPLICATION_STATUSES = {
    "APPLIED",
    "SCREENING",
    "INTERVIEW",
    "OFFER",
    "HIRED",
    "REJECTED",
    "WITHDRAWN",
    "ON_HOLD",
}


def require_candidate(
    db: Session,
    candidate_id: str,
    owner_sub: str,
):
    candidate = candidates_repository.get_candidate(
        db,
        candidate_id,
        owner_sub=owner_sub,
    )
    if candidate is None:
        raise CandidateNotFound(candidate_id)
    return candidate


def require_job(
    db: Session,
    job_id: str,
    owner_sub: str,
):
    job = jobs_repository.get_job(db, job_id, owner_sub=owner_sub)
    if job is None:
        raise JobNotFound(job_id)
    return job


def list_candidates(db: Session, owner_sub: str):
    return candidates_repository.list_candidates(db, owner_sub=owner_sub)


def list_candidates_page(
    db: Session,
    owner_sub: str,
    *,
    page: int = 1,
    page_size: int = 20,
):
    return candidates_repository.list_candidates_page(
        db,
        owner_sub=owner_sub,
        page=page,
        page_size=page_size,
    )


def list_job_candidates(
    db: Session,
    job_id: str,
    owner_sub: str,
    *,
    page: int = 1,
    page_size: int = 10,
):
    require_job(db, job_id, owner_sub)
    return candidates_repository.list_candidates_for_job(
        db,
        job_id,
        page=page,
        page_size=page_size,
        owner_sub=owner_sub,
    )


def assign_candidates(
    db: Session,
    job_id: str,
    candidate_ids: list[str],
    owner_sub: str,
):
    require_job(db, job_id, owner_sub)
    return candidates_repository.assign_candidates_to_job(
        db,
        job_id,
        candidate_ids,
        owner_sub=owner_sub,
    )


def set_application_status(
    db: Session,
    *,
    job_id: str,
    candidate_id: str,
    status: str,
    owner_sub: str,
):
    require_job(db, job_id, owner_sub)
    require_candidate(db, candidate_id, owner_sub)
    link = candidates_repository.get_job_candidate(
        db,
        job_id=job_id,
        candidate_id=candidate_id,
        owner_sub=owner_sub,
    )
    if link is None:
        raise JobCandidateNotFound(candidate_id)

    normalized = (status or "").strip().upper()
    if normalized not in APPLICATION_STATUSES:
        raise InvalidApplicationStatus(status)
    if link.application_status == normalized:
        return link, False

    candidates_repository.set_job_candidate_status(db, link, status=normalized)

    # Keep provider mapping out of the core model. The Indeed adapter only
    # receives a provider-neutral local status after the local state changed.
    from app.domains.indeed import service as indeed_service

    indeed_service.queue_candidate_status(
        db,
        owner_sub=owner_sub,
        job_id=job_id,
        candidate_id=candidate_id,
        local_status=normalized,
        status_changed_at=link.status_changed_at,
    )
    db.commit()
    db.refresh(link)
    return link, True


def get_job_candidate_evaluation(
    db: Session,
    job_id: str,
    candidate_id: str,
    owner_sub: str,
):
    require_job(db, job_id, owner_sub)
    require_candidate(db, candidate_id, owner_sub)
    return evaluations_repository.get_evaluation_for_job_candidate(
        db,
        job_id,
        candidate_id,
    )


def get_candidate_evaluations(
    db: Session,
    candidate_id: str,
    owner_sub: str,
):
    require_candidate(db, candidate_id, owner_sub)
    return evaluations_repository.get_evaluations_for_candidate(db, candidate_id)


def get_candidate_download(
    db: Session,
    candidate_id: str,
    owner_sub: str,
) -> dict | None:
    """Return a short-lived URL only after owner-scoped candidate authorization."""
    require_candidate(db, candidate_id, owner_sub)
    return create_canonical_candidate_download(candidate_id)


def delete_candidate(
    db: Session,
    candidate_id: str,
    owner_sub: str,
) -> bool:
    require_candidate(db, candidate_id, owner_sub)
    raise CandidateRetentionProtected(
        "Candidate hard-delete is disabled by retention policy."
    )


def delete_all_candidates(db: Session, owner_sub: str) -> tuple[int, int]:
    raise CandidateRetentionProtected(
        "Bulk candidate hard-delete is disabled by retention policy."
    )


def set_candidate_ban(
    db: Session,
    *,
    candidate_id: str,
    owner_sub: str,
    reason: str,
    created_by_sub: str,
    banned: bool,
):
    candidate = require_candidate(db, candidate_id, owner_sub)
    return candidates_repository.set_candidate_restriction(
        db,
        candidate,
        is_banned=banned,
        reason=reason.strip(),
        created_by_sub=created_by_sub,
    )


def get_candidate_restriction_history(
    db: Session,
    *,
    candidate_id: str,
    owner_sub: str,
):
    candidate = require_candidate(db, candidate_id, owner_sub)
    events = candidates_repository.list_candidate_restriction_events(
        db,
        candidate_id=candidate.id,
    )
    return candidate, events


def _legacy_pdf_filename(original_filename: str | None) -> str:
    safe_name = str(original_filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not safe_name or not safe_name.casefold().endswith(".pdf"):
        raise LegacyCandidateUploadError("LEGACY_UPLOAD_PDF_ONLY")
    return safe_name


def validate_legacy_candidate_pdf(
    *,
    original_filename: str | None,
    file_content: bytes,
) -> str:
    """Validate the legacy endpoint's PDF-only storage contract."""
    safe_name = _legacy_pdf_filename(original_filename)
    if not file_content:
        raise LegacyCandidateUploadError("LEGACY_UPLOAD_EMPTY")
    if len(file_content) > MAX_DOCUMENT_BYTES:
        raise LegacyCandidateUploadError("LEGACY_UPLOAD_TOO_LARGE")
    try:
        parsed = extract_document(file_content, safe_name)
    except DocumentImportError as exc:
        raise LegacyCandidateUploadError("LEGACY_UPLOAD_INVALID_PDF") from exc
    if parsed.content_type != PDF_CONTENT_TYPE:
        raise LegacyCandidateUploadError("LEGACY_UPLOAD_PDF_ONLY")
    return safe_name


def create_and_index_candidate(
    db: Session,
    *,
    owner_sub: str,
    original_filename: str | None,
    file_content: bytes,
):
    safe_filename = _legacy_pdf_filename(original_filename)
    name = os.path.splitext(safe_filename)[0]
    candidate = candidates_repository.create_candidate(
        db,
        name=name,
        metadata={"filename": safe_filename},
        owner_sub=owner_sub,
    )
    indexing = index_candidate_document(
        candidate,
        file_content,
        safe_filename,
    )
    return candidate, indexing


__all__ = [
    "APPLICATION_STATUSES",
    "LegacyCandidateUploadError",
    "validate_legacy_candidate_pdf",
    "CandidateNotFound",
    "InvalidApplicationStatus",
    "JobCandidateNotFound",
    "JobNotFound",
    "require_candidate",
    "require_job",
    "list_candidates",
    "list_candidates_page",
    "list_job_candidates",
    "assign_candidates",
    "set_application_status",
    "get_job_candidate_evaluation",
    "get_candidate_evaluations",
    "get_candidate_download",
    "delete_candidate",
    "delete_all_candidates",
    "set_candidate_ban",
    "get_candidate_restriction_history",
    "create_and_index_candidate",
]
