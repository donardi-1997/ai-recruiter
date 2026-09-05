"""CRUD operations — transaction management and advisory locks."""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Candidate, Evaluation, Job, JobCandidate, Ranking, RankingItem

logger = logging.getLogger(__name__)


# ============================================================
# JOBS
# ============================================================

def get_job(db: Session, job_id: str) -> Job | None:
    return db.query(Job).filter(Job.id == job_id).first()


def list_jobs(db: Session) -> list[Job]:
    return db.query(Job).order_by(Job.created_at.desc()).all()


def create_job(db: Session, *, title: str, description: str | None = None) -> Job:
    job = Job(title=title, description=description)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


# ============================================================
# CANDIDATES
# ============================================================

def get_candidate(db: Session, candidate_id: str) -> Candidate | None:
    return db.query(Candidate).filter(Candidate.id == candidate_id).first()


def list_candidates(db: Session) -> list[Candidate]:
    return db.query(Candidate).order_by(Candidate.created_at.desc()).all()


def create_candidate(
    db: Session,
    *,
    name: str,
    email: str | None = None,
    metadata: dict | None = None,
) -> Candidate:
    candidate = Candidate(name=name, email=email, metadata_=metadata or {})
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


def delete_candidate(db: Session, candidate_id: str) -> bool:
    candidate = get_candidate(db, candidate_id)
    if not candidate:
        return False
    db.delete(candidate)
    db.commit()
    return True


def delete_all_candidates(db: Session) -> tuple[int, int]:
    count = db.query(Candidate).count()
    db.query(Candidate).delete()
    db.commit()
    return count, 0


def list_candidates_for_job(
    db: Session,
    job_id: str,
    *,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[Candidate], int]:
    """List candidates assigned to a given job."""
    query = (
        db.query(Candidate)
        .join(JobCandidate, JobCandidate.candidate_id == Candidate.id)
        .filter(JobCandidate.job_id == job_id)
        .order_by(Candidate.name)
    )
    total = query.count() or 0
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, total


# ============================================================
# JOB-CANDIDATE ASSIGNMENT
# ============================================================

def assign_candidates_to_job(
    db: Session,
    job_id: str,
    candidate_ids: list[str],
) -> tuple[int, int]:
    assigned = 0
    skipped = 0
    for cid in candidate_ids:
        existing = (
            db.query(JobCandidate)
            .filter(JobCandidate.job_id == job_id, JobCandidate.candidate_id == cid)
            .first()
        )
        if existing:
            skipped += 1
            continue
        db.add(JobCandidate(job_id=job_id, candidate_id=cid))
        assigned += 1
    db.commit()
    return assigned, skipped


# ============================================================
# EVALUATIONS
# ============================================================

def create_evaluation(
    db: Session,
    *,
    candidate_id: str,
    job_id: str,
    match_score: float,
    recommendation: str,
    summary: str,
    strengths: list[str],
    gaps: list[str],
) -> Evaluation:
    evaluation = Evaluation(
        candidate_id=candidate_id,
        job_id=job_id,
        match_score=match_score,
        recommendation=recommendation,
        summary=summary,
        strengths=strengths,
        gaps=gaps,
    )
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)
    return evaluation


# ============================================================
# RANKING
# ============================================================

def get_ranking_metadata(db: Session, job_id: str) -> Ranking | None:
    return (
        db.query(Ranking)
        .filter(Ranking.job_id == job_id)
        .order_by(Ranking.ranking_version.desc())
        .first()
    )


def upsert_ranking_metadata(
    db: Session,
    job_id: str,
    version: int,
    mode: str = "full",
) -> Ranking:
    now = datetime.now(timezone.utc)
    existing = get_ranking_metadata(db, job_id)

    if existing:
        existing.generated_at = now
        existing.ranking_version = version
        existing.mode = mode
    else:
        existing = Ranking(
            job_id=job_id,
            ranking_version=version,
            generated_at=now,
            mode=mode,
        )
        db.add(existing)

    db.commit()
    db.refresh(existing)
    return existing


def insert_ranking_items(
    db: Session,
    *,
    ranking_id: str,
    items: list[dict[str, Any]],
) -> int:
    count = 0
    for item in items:
        db.add(
            RankingItem(
                ranking_id=ranking_id,
                candidate_id=item["candidate_id"],
                score=item["score"],
                position=item["position"],
            )
        )
        count += 1
    db.commit()
    return count


def get_ranking_items(
    db: Session,
    ranking_id: str,
) -> list[RankingItem]:
    return (
        db.query(RankingItem)
        .filter(RankingItem.ranking_id == ranking_id)
        .order_by(RankingItem.position)
        .all()
    )


def build_ranking_response(
    db: Session,
    job_id: str,
    *,
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    job = get_job(db, job_id)
    meta = get_ranking_metadata(db, job_id)

    if meta:
        items_query = (
            db.query(RankingItem)
            .filter(RankingItem.ranking_id == meta.id)
        )
        total = items_query.count() or 0
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0

        items = (
            items_query
            .order_by(RankingItem.position)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        candidates = [
            {
                "position": item.position,
                "candidate_id": item.candidate_id,
                "score": item.score,
                "candidate_name": item.candidate.name if item.candidate else "",
            }
            for item in items
        ]
    else:
        total = 0
        total_pages = 0
        candidates = []

    return {
        "job_id": job_id,
        "job_title": job.title if job else "",
        "ranking_generated_at": (
            meta.generated_at.isoformat()
            if meta and meta.generated_at
            else None
        ),
        "ranking_version": (meta.ranking_version if meta else None),
        "total": total,
        "total_pages": total_pages,
        "page": page,
        "page_size": page_size,
        "pending_candidates": 0,
        "candidates": candidates,
    }
