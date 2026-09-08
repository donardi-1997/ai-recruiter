"""Candidates repository."""

from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models import Candidate, Evaluation, JobCandidate, RankingItem


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


def delete_candidate(db: Session, candidate_id: str) -> bool:
    candidate = get_candidate(db, candidate_id)
    if not candidate:
        return False
    db.query(JobCandidate).filter(JobCandidate.candidate_id == candidate_id).delete()
    db.query(Evaluation).filter(Evaluation.candidate_id == candidate_id).delete()
    db.query(RankingItem).filter(RankingItem.candidate_id == candidate_id).delete()
    db.delete(candidate)
    db.commit()
    return True


def delete_all_candidates(db: Session, owner_sub: str | None = None) -> tuple[int, int]:
    query = db.query(Candidate)
    if owner_sub is not None:
        query = query.filter(Candidate.owner_sub == owner_sub)

    candidate_ids = [candidate_id for (candidate_id,) in query.with_entities(Candidate.id).all()]
    count = len(candidate_ids)

    if not candidate_ids:
        return 0, 0

    db.query(JobCandidate).filter(JobCandidate.candidate_id.in_(candidate_ids)).delete(synchronize_session=False)
    db.query(Evaluation).filter(Evaluation.candidate_id.in_(candidate_ids)).delete(synchronize_session=False)
    db.query(RankingItem).filter(RankingItem.candidate_id.in_(candidate_ids)).delete(synchronize_session=False)
    db.query(Candidate).filter(Candidate.id.in_(candidate_ids)).delete(synchronize_session=False)
    db.commit()
    return count, 0


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

    allowed_ids = {candidate_id for (candidate_id,) in candidate_query.all()}

    for cid in candidate_ids:
        if cid not in allowed_ids:
            skipped += 1
            continue

        existing = db.query(JobCandidate).filter(JobCandidate.job_id == job_id, JobCandidate.candidate_id == cid).first()
        if existing:
            skipped += 1
            continue

        db.add(JobCandidate(job_id=job_id, candidate_id=cid))
        assigned += 1

    db.commit()
    return assigned, skipped