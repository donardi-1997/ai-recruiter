"""Persistence primitives for durable candidate imports."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domains.candidate_imports.exceptions import IdentityConflict
from app.models import Candidate, CandidateIdentity, ImportBatch, ImportItem


TERMINAL_BATCH_STATUSES = ("COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED")


def create_batch_record(
    db: Session,
    *,
    owner_sub: str,
    job_id: str,
    upload_total: int,
    total_items: int,
) -> ImportBatch:
    batch = ImportBatch(
        owner_sub=owner_sub,
        job_id=job_id,
        status="UPLOADING",
        current_stage="UPLOADING",
        upload_total=upload_total,
        total_items=total_items,
    )
    db.add(batch)
    db.flush()
    return batch


def create_item(
    db: Session,
    *,
    item_id: str,
    batch_id: str,
    kind: str,
    original_filename: str,
    staging_s3_key: str,
    content_type: str,
    size_bytes: int,
    parent_item_id: str | None = None,
) -> ImportItem:
    item = ImportItem(
        id=item_id,
        batch_id=batch_id,
        parent_item_id=parent_item_id,
        kind=kind,
        original_filename=original_filename,
        staging_s3_key=staging_s3_key,
        content_type=content_type,
        size_bytes=size_bytes,
        status="UPLOADING",
        current_stage="UPLOADING",
    )
    db.add(item)
    db.flush()
    return item


def get_batch(db: Session, batch_id: str, owner_sub: str) -> ImportBatch | None:
    return (
        db.query(ImportBatch)
        .filter(ImportBatch.id == batch_id, ImportBatch.owner_sub == owner_sub)
        .first()
    )


def get_batch_for_worker(db: Session, batch_id: str) -> ImportBatch | None:
    """Load a batch by its durable queue identifier for trusted worker code."""
    return db.query(ImportBatch).filter(ImportBatch.id == batch_id).first()


def claim_batch(
    db: Session,
    *,
    batch_id: str,
    token: str,
    now: datetime,
    lease_seconds: int,
) -> bool:
    """Atomically claim an unleased or stale non-terminal import batch."""
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")

    stale_before = now - timedelta(seconds=lease_seconds)
    updated = (
        db.query(ImportBatch)
        .filter(
            ImportBatch.id == batch_id,
            ~ImportBatch.status.in_(TERMINAL_BATCH_STATUSES),
            or_(
                ImportBatch.processing_token.is_(None),
                ImportBatch.heartbeat_at.is_(None),
                ImportBatch.heartbeat_at < stale_before,
            ),
        )
        .update(
            {
                ImportBatch.processing_token: token,
                ImportBatch.heartbeat_at: now,
                ImportBatch.attempt_count: ImportBatch.attempt_count + 1,
                ImportBatch.started_at: func.coalesce(ImportBatch.started_at, now),
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return updated == 1


def heartbeat_batch(
    db: Session,
    *,
    batch_id: str,
    token: str,
    now: datetime,
) -> None:
    """Refresh a lease only when the caller still owns its processing token."""
    (
        db.query(ImportBatch)
        .filter(
            ImportBatch.id == batch_id,
            ImportBatch.processing_token == token,
            ~ImportBatch.status.in_(TERMINAL_BATCH_STATUSES),
        )
        .update(
            {ImportBatch.heartbeat_at: now},
            synchronize_session=False,
        )
    )
    db.commit()


def release_batch_lease(
    db: Session,
    *,
    batch_id: str,
    token: str,
) -> None:
    """Release a lease only when the supplied token still owns it."""
    (
        db.query(ImportBatch)
        .filter(
            ImportBatch.id == batch_id,
            ImportBatch.processing_token == token,
        )
        .update(
            {
                ImportBatch.processing_token: None,
                ImportBatch.heartbeat_at: None,
            },
            synchronize_session=False,
        )
    )
    db.commit()


def list_undispatched_queued_batches(db: Session) -> list[ImportBatch]:
    """Return durable queued batches whose SQS dispatch was not checkpointed."""
    return (
        db.query(ImportBatch)
        .filter(
            ImportBatch.status == "QUEUED",
            ImportBatch.queue_dispatched_at.is_(None),
        )
        .order_by(ImportBatch.created_at.asc(), ImportBatch.id.asc())
        .all()
    )


def list_batch_items(
    db: Session,
    *,
    batch_id: str,
    owner_sub: str,
    page: int,
    page_size: int,
) -> tuple[list[ImportItem], int]:
    query = (
        db.query(ImportItem)
        .join(ImportBatch, ImportBatch.id == ImportItem.batch_id)
        .filter(
            ImportItem.batch_id == batch_id,
            ImportBatch.owner_sub == owner_sub,
        )
        .order_by(ImportItem.created_at.asc(), ImportItem.id.asc())
    )
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, total


def list_top_level_items(
    db: Session,
    *,
    batch_id: str,
    owner_sub: str,
) -> list[ImportItem]:
    return (
        db.query(ImportItem)
        .join(ImportBatch, ImportBatch.id == ImportItem.batch_id)
        .filter(
            ImportItem.batch_id == batch_id,
            ImportItem.parent_item_id.is_(None),
            ImportBatch.owner_sub == owner_sub,
        )
        .order_by(ImportItem.created_at.asc(), ImportItem.id.asc())
        .all()
    )


def list_recent_batches(
    db: Session,
    *,
    owner_sub: str,
    job_id: str,
    limit: int,
) -> list[ImportBatch]:
    return (
        db.query(ImportBatch)
        .filter(
            ImportBatch.owner_sub == owner_sub,
            ImportBatch.job_id == job_id,
        )
        .order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc())
        .limit(limit)
        .all()
    )


def find_identity(
    db: Session,
    *,
    owner_sub: str,
    kind: str,
    value: str,
) -> CandidateIdentity | None:
    return (
        db.query(CandidateIdentity)
        .filter(
            CandidateIdentity.owner_sub == owner_sub,
            CandidateIdentity.kind == kind,
            CandidateIdentity.value == value,
        )
        .first()
    )


def attach_identity(
    db: Session,
    *,
    owner_sub: str,
    candidate_id: str,
    kind: str,
    value: str,
) -> CandidateIdentity:
    """Attach an identity using a savepoint so unique races are conservative."""
    existing = find_identity(
        db,
        owner_sub=owner_sub,
        kind=kind,
        value=value,
    )
    if existing is not None:
        if existing.candidate_id == candidate_id:
            return existing
        raise IdentityConflict("IDENTITY_CONFLICT")

    identity = CandidateIdentity(
        owner_sub=owner_sub,
        candidate_id=candidate_id,
        kind=kind,
        value=value,
    )
    try:
        with db.begin_nested():
            db.add(identity)
            db.flush()
        return identity
    except IntegrityError:
        winner = find_identity(
            db,
            owner_sub=owner_sub,
            kind=kind,
            value=value,
        )
        if winner is not None and winner.candidate_id == candidate_id:
            return winner
        raise IdentityConflict("IDENTITY_CONFLICT") from None


def find_legacy_candidates_by_normalized_email(
    db: Session,
    *,
    owner_sub: str,
    normalized_email: str,
) -> list[Candidate]:
    """Find pre-identity-table candidates without crossing owner boundaries."""
    return (
        db.query(Candidate)
        .filter(
            Candidate.owner_sub == owner_sub,
            Candidate.email.isnot(None),
            func.lower(func.trim(Candidate.email)) == normalized_email,
        )
        .order_by(Candidate.created_at.asc(), Candidate.id.asc())
        .all()
    )
