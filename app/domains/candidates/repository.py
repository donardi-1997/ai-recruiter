"""Candidates repository."""

from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domains.candidates.exceptions import CandidateRetentionProtected
from app.models import (
    Candidate,
    CandidateRestrictionEvent,
    Evaluation,
    JobCandidate,
    RankingItem,
)


def get_candidate(db: Session, candidate_id: str, owner_sub: str | None = None) -> Candidate | None:
    query = db.query(Candidate).filter(Candidate.id == candidate_id)
    if owner_sub is not None:
        query = query.filter(Candidate.owner_sub == owner_sub)
    return query.first()


def list_candidates(db: Session, owner_sub: str | None = None) -> list[Candidate]:
    query = db.query(Candidate)
    if owner_sub is not None:
        query = query.filter(Candidate.owner_sub == owner_sub)
    return query.order_by(Candidate.created_at.desc()).all()


def list_candidates_page(
    db: Session,
    *,
    owner_sub: str,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Candidate], int]:
    """Return one stable owner-scoped candidate page and its total count."""
    query = db.query(Candidate).filter(Candidate.owner_sub == owner_sub)
    total = query.count() or 0
    items = (
        query.order_by(Candidate.created_at.desc(), Candidate.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def count_candidates(
    db: Session,
    *,
    owner_sub: str,
    include_banned: bool = False,
) -> int:
    query = db.query(Candidate).filter(Candidate.owner_sub == owner_sub)
    if not include_banned:
        query = query.filter(Candidate.is_banned.is_(False))
    return int(query.count() or 0)


def count_candidates_for_job(
    db: Session,
    *,
    job_id: str,
    owner_sub: str,
    include_banned: bool = False,
) -> int:
    query = (
        db.query(Candidate)
        .join(JobCandidate, JobCandidate.candidate_id == Candidate.id)
        .filter(
            JobCandidate.job_id == job_id,
            Candidate.owner_sub == owner_sub,
        )
    )
    if not include_banned:
        query = query.filter(Candidate.is_banned.is_(False))
    return int(query.count() or 0)


def create_candidate(
    db: Session,
    *,
    name: str,
    email: str | None = None,
    metadata: dict | None = None,
    owner_sub: str | None = None,
) -> Candidate:
    candidate = Candidate(name=name, email=email, metadata_=metadata or {}, owner_sub=owner_sub)
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


def create_candidate_pending(
    db: Session,
    *,
    name: str,
    email: str | None = None,
    metadata: dict | None = None,
    owner_sub: str,
) -> Candidate:
    """Create a candidate inside the caller-owned transaction."""
    candidate = Candidate(
        name=name,
        email=email,
        metadata_=metadata or {},
        owner_sub=owner_sub,
    )
    db.add(candidate)
    db.flush()
    return candidate


def update_candidate_document_metadata(
    db: Session,
    candidate: Candidate,
    *,
    filename: str,
    email: str | None,
) -> Candidate:
    """Update document metadata without replacing a different known email."""
    metadata = dict(candidate.metadata_ or {})
    metadata["filename"] = filename
    candidate.metadata_ = metadata
    if not candidate.email and email:
        candidate.email = email
    db.flush()
    return candidate


def ensure_candidate_assigned_to_job(
    db: Session,
    *,
    job_id: str,
    candidate_id: str,
) -> JobCandidate:
    """Idempotently assign a candidate to a job inside the caller transaction."""
    existing = (
        db.query(JobCandidate)
        .filter(
            JobCandidate.job_id == job_id,
            JobCandidate.candidate_id == candidate_id,
        )
        .first()
    )
    if existing is not None:
        return existing
    link = JobCandidate(job_id=job_id, candidate_id=candidate_id)
    savepoint = db.begin_nested()
    try:
        db.add(link)
        db.flush()
        savepoint.commit()
        return link
    except IntegrityError:
        savepoint.rollback()
        existing = (
            db.query(JobCandidate)
            .filter(
                JobCandidate.job_id == job_id,
                JobCandidate.candidate_id == candidate_id,
            )
            .first()
        )
        if existing is not None:
            return existing
        raise


def get_job_candidate(
    db: Session,
    *,
    job_id: str,
    candidate_id: str,
    owner_sub: str | None = None,
) -> JobCandidate | None:
    query = (
        db.query(JobCandidate)
        .join(Candidate, Candidate.id == JobCandidate.candidate_id)
        .filter(
            JobCandidate.job_id == job_id,
            JobCandidate.candidate_id == candidate_id,
        )
    )
    if owner_sub is not None:
        query = query.filter(Candidate.owner_sub == owner_sub)
    return query.first()


def set_job_candidate_status(
    db: Session,
    link: JobCandidate,
    *,
    status: str,
    changed_at: datetime | None = None,
) -> JobCandidate:
    link.application_status = status
    link.status_changed_at = changed_at or datetime.now(timezone.utc)
    db.flush()
    return link


def delete_candidate(db: Session, candidate_id: str) -> bool:
    raise CandidateRetentionProtected(
        "Candidate hard-delete is disabled by retention policy."
    )


def delete_all_candidates(db: Session, owner_sub: str | None = None) -> tuple[int, int]:
    raise CandidateRetentionProtected(
        "Bulk candidate hard-delete is disabled by retention policy."
    )


def set_candidate_restriction(
    db: Session,
    candidate: Candidate,
    *,
    is_banned: bool,
    reason: str,
    created_by_sub: str,
) -> tuple[Candidate, CandidateRestrictionEvent | None, bool]:
    if bool(candidate.is_banned) == bool(is_banned):
        return candidate, None, False

    now = datetime.now(timezone.utc)
    candidate.is_banned = bool(is_banned)
    candidate.banned_at = now if is_banned else None
    candidate.banned_by_sub = created_by_sub if is_banned else None
    candidate.banned_reason = reason if is_banned else None

    event = CandidateRestrictionEvent(
        candidate_id=candidate.id,
        action="BANNED" if is_banned else "UNBANNED",
        reason=reason,
        created_by_sub=created_by_sub,
        created_at=now,
    )
    db.add(event)
    db.commit()
    db.refresh(candidate)
    db.refresh(event)
    return candidate, event, True


def list_candidate_restriction_events(
    db: Session,
    *,
    candidate_id: str,
) -> list[CandidateRestrictionEvent]:
    return (
        db.query(CandidateRestrictionEvent)
        .filter(CandidateRestrictionEvent.candidate_id == candidate_id)
        .order_by(
            CandidateRestrictionEvent.created_at.desc(),
            CandidateRestrictionEvent.id.desc(),
        )
        .all()
    )


def list_candidates_for_job(
    db: Session,
    job_id: str,
    *,
    page: int = 1,
    page_size: int = 10,
    owner_sub: str | None = None,
) -> tuple[list[Candidate], int]:
    query = db.query(Candidate).join(JobCandidate, JobCandidate.candidate_id == Candidate.id).filter(JobCandidate.job_id == job_id)
    if owner_sub is not None:
        query = query.filter(Candidate.owner_sub == owner_sub)
    query = query.order_by(Candidate.name)
    total = query.count() or 0
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, total


def assign_candidates_to_job(
    db: Session,
    job_id: str,
    candidate_ids: list[str],
    owner_sub: str | None = None,
) -> tuple[int, int]:
    assigned = 0
    skipped = 0

    candidate_query = db.query(Candidate.id).filter(Candidate.id.in_(candidate_ids))
    if owner_sub is not None:
        candidate_query = candidate_query.filter(Candidate.owner_sub == owner_sub)

    candidate_query = candidate_query.filter(Candidate.is_banned.is_(False))
    allowed_ids = {candidate_id for (candidate_id,) in candidate_query.all()}

    for cid in candidate_ids:
        if cid not in allowed_ids:
            skipped += 1
            continue

        existing = db.query(JobCandidate).filter(JobCandidate.job_id == job_id, JobCandidate.candidate_id == cid).first()
        if existing:
            skipped += 1
            continue

        savepoint = db.begin_nested()
        try:
            db.add(JobCandidate(job_id=job_id, candidate_id=cid))
            db.flush()
            savepoint.commit()
            assigned += 1
        except IntegrityError:
            savepoint.rollback()
            skipped += 1

    db.commit()
    return assigned, skipped
