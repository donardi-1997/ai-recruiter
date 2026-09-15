"""Application service for durable job-scoped candidate imports."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath

from sqlalchemy.orm import Session

from app.domains.candidate_imports import repository, rules
from app.domains.candidate_imports.exceptions import (
    IdentityConflict,
    ImportBatchNotFound,
    InvalidImportManifest,
    JobNotFound,
    QueueDispatchFailed,
    UploadVerificationFailed,
)
from app.domains.candidates import repository as candidates_repository
from app.domains.jobs import repository as jobs_repository
from app.infrastructure.imports import queue, storage
from app.infrastructure.imports.documents import ParsedDocument
from app.models import Candidate, ImportBatch, ImportItem

MIB = 1024 * 1024
MAX_DOCUMENT_BYTES = 15 * MIB
MAX_ARCHIVE_BYTES = 500 * MIB
MAX_DIRECT_DOCUMENTS = 500

PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
ZIP_CONTENT_TYPES = {
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
}


def _extension(filename: str) -> str:
    return PurePosixPath(filename.replace("\\", "/")).suffix.casefold()


def _validate_upload(upload: dict) -> tuple[str, str]:
    filename = str(upload.get("filename") or "").strip()
    content_type = str(upload.get("content_type") or "").strip().casefold()
    try:
        size_bytes = int(upload.get("size_bytes"))
    except (TypeError, ValueError):
        raise InvalidImportManifest("INVALID_UPLOAD_SIZE") from None

    if not filename or size_bytes <= 0 or not content_type:
        raise InvalidImportManifest("INVALID_UPLOAD")

    extension = _extension(filename)
    if extension == ".pdf":
        if size_bytes > MAX_DOCUMENT_BYTES:
            raise InvalidImportManifest("DOCUMENT_TOO_LARGE")
        if content_type not in {PDF_CONTENT_TYPE, "application/octet-stream"}:
            raise InvalidImportManifest("INVALID_CONTENT_TYPE")
        return "DOCUMENT", extension

    if extension == ".docx":
        if size_bytes > MAX_DOCUMENT_BYTES:
            raise InvalidImportManifest("DOCUMENT_TOO_LARGE")
        if content_type not in {DOCX_CONTENT_TYPE, "application/octet-stream"}:
            raise InvalidImportManifest("INVALID_CONTENT_TYPE")
        return "DOCUMENT", extension

    if extension == ".zip":
        if size_bytes > MAX_ARCHIVE_BYTES:
            raise InvalidImportManifest("ARCHIVE_TOO_LARGE")
        if content_type not in ZIP_CONTENT_TYPES:
            raise InvalidImportManifest("INVALID_CONTENT_TYPE")
        return "ARCHIVE", extension

    raise InvalidImportManifest("UNSUPPORTED_DOCUMENT")


def _require_job(db: Session, *, owner_sub: str, job_id: str):
    job = jobs_repository.get_job(db, job_id, owner_sub=owner_sub)
    if job is None:
        raise JobNotFound("JOB_NOT_FOUND")
    return job


def _require_batch(db: Session, *, owner_sub: str, batch_id: str) -> ImportBatch:
    batch = repository.get_batch(db, batch_id=batch_id, owner_sub=owner_sub)
    if batch is None:
        raise ImportBatchNotFound("IMPORT_BATCH_NOT_FOUND")
    return batch


def create_batch(
    db: Session,
    *,
    owner_sub: str,
    job_id: str,
    uploads: list[dict],
) -> tuple[ImportBatch, list[dict]]:
    """Create an UPLOADING batch and fixed presigned S3 upload manifest."""
    _require_job(db, owner_sub=owner_sub, job_id=job_id)
    if not uploads:
        raise InvalidImportManifest("EMPTY_IMPORT_MANIFEST")

    validated: list[tuple[dict, str]] = []
    direct_documents = 0
    for upload in uploads:
        kind, _ = _validate_upload(upload)
        validated.append((upload, kind))
        if kind == "DOCUMENT":
            direct_documents += 1
    if direct_documents > MAX_DIRECT_DOCUMENTS:
        raise InvalidImportManifest("DOCUMENT_LIMIT_EXCEEDED")

    try:
        batch = repository.create_batch_record(
            db,
            owner_sub=owner_sub,
            job_id=job_id,
            upload_total=len(uploads),
            total_items=direct_documents,
        )
        descriptors: list[dict] = []
        for upload, kind in validated:
            item_id = str(uuid.uuid4())
            signed = storage.create_staging_presigned_post(
                batch_id=batch.id,
                item_id=item_id,
                filename=str(upload["filename"]),
                content_type=str(upload["content_type"]),
                size_bytes=int(upload["size_bytes"]),
            )
            staging_key = str((signed.get("fields") or {}).get("key") or "")
            if not staging_key:
                raise RuntimeError("presigned upload did not contain a fixed key")

            repository.create_item(
                db,
                item_id=item_id,
                batch_id=batch.id,
                kind=kind,
                original_filename=str(upload["filename"]),
                staging_s3_key=staging_key,
                content_type=str(upload["content_type"]),
                size_bytes=int(upload["size_bytes"]),
            )
            descriptors.append(
                {
                    "item_id": item_id,
                    "filename": str(upload["filename"]),
                    "content_type": str(upload["content_type"]),
                    "size_bytes": int(upload["size_bytes"]),
                    "upload": signed,
                }
            )

        db.commit()
        db.refresh(batch)
        return batch, descriptors
    except Exception:
        db.rollback()
        raise


def _dispatch_if_needed(db: Session, batch: ImportBatch) -> ImportBatch:
    if batch.status != "QUEUED" or batch.queue_dispatched_at is not None:
        return batch
    try:
        queue.send_import_batch(batch.id)
    except Exception:
        # The QUEUED commit intentionally remains durable for retry/worker repair.
        raise QueueDispatchFailed("QUEUE_DISPATCH_FAILED") from None

    batch.queue_dispatched_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(batch)
    return batch


def complete_batch_uploads(
    db: Session,
    *,
    owner_sub: str,
    batch_id: str,
) -> ImportBatch:
    """Verify declared staging objects, durably queue, then dispatch to SQS."""
    batch = _require_batch(db, owner_sub=owner_sub, batch_id=batch_id)

    if batch.status == "UPLOADING":
        items = repository.list_top_level_items(
            db,
            batch_id=batch.id,
            owner_sub=owner_sub,
        )
        if len(items) != batch.upload_total:
            raise UploadVerificationFailed("UPLOAD_VERIFICATION_FAILED")

        for item in items:
            try:
                metadata = storage.head_staging_object(item.staging_s3_key)
                actual_size = int(metadata.get("ContentLength", -1))
            except Exception:
                raise UploadVerificationFailed("UPLOAD_VERIFICATION_FAILED") from None
            if actual_size != item.size_bytes:
                raise UploadVerificationFailed("UPLOAD_VERIFICATION_FAILED")

        for item in items:
            item.status = "UPLOADED"
            item.current_stage = "UPLOADING"
        batch.uploaded_items = len(items)
        batch.status = "QUEUED"
        batch.current_stage = "UPLOADING"
        batch.queue_dispatched_at = None
        db.commit()
        db.refresh(batch)

    return _dispatch_if_needed(db, batch)


def get_batch(db: Session, *, owner_sub: str, batch_id: str) -> ImportBatch:
    return _require_batch(db, owner_sub=owner_sub, batch_id=batch_id)


def list_batch_items(
    db: Session,
    *,
    owner_sub: str,
    batch_id: str,
    page: int,
    page_size: int,
) -> tuple[list[ImportItem], int]:
    _require_batch(db, owner_sub=owner_sub, batch_id=batch_id)
    return repository.list_batch_items(
        db,
        batch_id=batch_id,
        owner_sub=owner_sub,
        page=page,
        page_size=page_size,
    )


def list_recent_batches(
    db: Session,
    *,
    owner_sub: str,
    job_id: str,
    limit: int,
) -> list[ImportBatch]:
    _require_job(db, owner_sub=owner_sub, job_id=job_id)
    return repository.list_recent_batches(
        db,
        owner_sub=owner_sub,
        job_id=job_id,
        limit=limit,
    )


def _strong_identity_values(parsed_document: ParsedDocument) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    if parsed_document.sha256:
        values.append(("DOCUMENT_SHA256", parsed_document.sha256.casefold()))
    if parsed_document.email:
        email = rules.normalize_email(parsed_document.email)
        if email:
            values.append(("EMAIL", email))
    if parsed_document.phone:
        phone = rules.normalize_phone(parsed_document.phone)
        if phone:
            values.append(("PHONE", phone))
    return values


def resolve_or_create_candidate(
    db: Session,
    *,
    owner_sub: str,
    parsed_document: ParsedDocument,
    batch_id: str,
) -> tuple[Candidate, str]:
    """Resolve strong owner-scoped identities or create a new candidate safely."""
    batch = _require_batch(db, owner_sub=owner_sub, batch_id=batch_id)
    identity_values = _strong_identity_values(parsed_document)
    matches: dict[str, str] = {}

    for kind, value in identity_values:
        identity = repository.find_identity(
            db,
            owner_sub=owner_sub,
            kind=kind,
            value=value,
        )
        if identity is not None:
            matches[kind] = identity.candidate_id

    normalized_email = (
        rules.normalize_email(parsed_document.email)
        if parsed_document.email
        else None
    )
    if normalized_email:
        legacy_candidates = repository.find_legacy_candidates_by_normalized_email(
            db,
            owner_sub=owner_sub,
            normalized_email=normalized_email,
        )
        if len(legacy_candidates) > 1:
            raise IdentityConflict("IDENTITY_CONFLICT")
        if legacy_candidates:
            matches["LEGACY_EMAIL"] = legacy_candidates[0].id

    resolved_candidate_id = rules.resolve_identity_candidates(matches)

    try:
        if resolved_candidate_id is None:
            candidate = candidates_repository.create_candidate_pending(
                db,
                name=parsed_document.display_name,
                email=normalized_email,
                metadata={"filename": parsed_document.filename},
                owner_sub=owner_sub,
            )
            outcome = "CREATED"
        else:
            candidate = candidates_repository.get_candidate(
                db,
                resolved_candidate_id,
                owner_sub=owner_sub,
            )
            if candidate is None:
                raise IdentityConflict("IDENTITY_CONFLICT")
            outcome = "REUSED"

        candidates_repository.update_candidate_document_metadata(
            db,
            candidate,
            filename=parsed_document.filename,
            email=normalized_email,
        )

        for kind, value in identity_values:
            repository.attach_identity(
                db,
                owner_sub=owner_sub,
                candidate_id=candidate.id,
                kind=kind,
                value=value,
            )

        candidates_repository.ensure_candidate_assigned_to_job(
            db,
            job_id=batch.job_id,
            candidate_id=candidate.id,
        )
        db.commit()
        db.refresh(candidate)
        return candidate, outcome
    except IdentityConflict:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
