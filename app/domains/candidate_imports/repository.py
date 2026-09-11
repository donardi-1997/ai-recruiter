"""Persistence primitives for durable candidate imports."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domains.candidate_imports.exceptions import IdentityConflict
from app.models import Candidate, CandidateIdentity, ImportBatch, ImportItem


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
