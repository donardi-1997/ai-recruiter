"""CRUD operations with transaction management.

Demonstrates advisory locking (pg_advisory_lock) to prevent
concurrent ranking recalculations for the same job_id.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import func, text, or_
from sqlalchemy.orm import Session

from pg_backend.models import (
    Candidate,
    Evaluation,
    Job,
    JobCandidate,
    Ranking,
    RankingItem,
)

logger = logging.getLogger(__name__)


# ============================================================
# ADVISORY LOCK HELPERS
# ============================================================

def _advisory_lock_key(job_id: str) -> int:
    """Deterministic integer from job_id for pg_advisory_lock.

    Uses the first 8 bytes of a SHA-256 digest to produce a
    signed 64-bit integer suitable for pg_advisory_lock(bigint).
    """
    import hashlib
    digest = hashlib.sha256(job_id.encode("utf-8")).digest()[:8]
    return int.from_bytes(digest, byteorder="big", signed=True)


def acquire_job_lock(db: Session, job_id: str) -> bool:
    """Acquire a session-level advisory lock for *job_id*.

    Returns True if the lock was acquired, False if another session
    already holds it.  The lock is released when the session ends or
    release_job_lock() is called.
    """
    lock_key = _advisory_lock_key(job_id)
    result = db.execute(
        text("SELECT pg_try_advisory_lock(:key)"),
        {"key": lock_key},
    ).scalar()
    logger.info(
        "Advisory lock job=%s key=%s acquired=%s",
        job_id,
        lock_key,
        result,
    )
    return bool(result)


def release_job_lock(db: Session, job_id: str) -> None:
    """Release the session-level advisory lock for *job_id*."""
    lock_key = _advisory_lock_key(job_id)
    db.execute(
        text("SELECT pg_advisory_unlock(:key)"),
        {"key": lock_key},
    )
    logger.info(
        "Advisory unlock job=%s key=%s",
        job_id,
        lock_key,
    )


# ============================================================
# JOBS
# ============================================================

def get_job(db: Session, job_id: str) -> Job | None:
    return db.query(Job).filter(Job.job_id == job_id).first()


def list_jobs_by_owner(db: Session, owner_id: str) -> list[Job]:
    return (
        db.query(Job)
        .filter(Job.owner_id == owner_id)
        .order_by(Job.created_at.desc())
        .all()
    )


def create_job(
    db: Session,
    job_id: str,
    owner_id: str,
    title: str,
    description: str,
) -> Job:
    job = Job(
        job_id=job_id,
        owner_id=owner_id,
        title=title,
        description=description,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


# ============================================================
# CANDIDATES
# ============================================================

def get_candidate(db: Session, candidate_id: str) -> Candidate | None:
    return (
        db.query(Candidate)
        .filter(Candidate.candidate_id == candidate_id)
        .first()
    )


def list_candidates_by_owner(db: Session, owner_id: str) -> list[Candidate]:
    return (
        db.query(Candidate)
        .filter(Candidate.owner_id == owner_id)
        .order_by(Candidate.created_at.desc())
        .all()
    )


def create_candidate(
    db: Session,
    candidate_id: str,
    owner_id: str,
    name: str,
    filename: str,
    s3_location: str,
    metadata_location: str | None = None,
) -> Candidate:
    candidate = Candidate(
        candidate_id=candidate_id,
        owner_id=owner_id,
        name=name,
        filename=filename,
        s3_location=s3_location,
        metadata_location=metadata_location,
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


# ============================================================
# JOB ↔ CANDIDATE (asignaciones)
# ============================================================

def assign_candidates_to_job(
    db: Session,
    job_id: str,
    owner_id: str,
    candidate_ids: list[str],
) -> list[JobCandidate]:
    """Insert job-candidate assignments.

    Skips duplicates gracefully (ON CONFLICT DO NOTHING via merge).
    """
    created: list[JobCandidate] = []
    for cid in candidate_ids:
        existing = (
            db.query(JobCandidate)
            .filter(
                JobCandidate.job_id == job_id,
                JobCandidate.candidate_id == cid,
            )
            .first()
        )
        if existing:
            continue
        link = JobCandidate(
            job_id=job_id,
            candidate_id=cid,
            owner_id=owner_id,
        )
        db.add(link)
        created.append(link)
    db.commit()
    return created


def get_job_candidate_ids(
    db: Session,
    job_id: str,
    owner_id: str,
) -> set[str]:
    rows = (
        db.query(JobCandidate.candidate_id)
        .filter(
            JobCandidate.job_id == job_id,
            JobCandidate.owner_id == owner_id,
        )
        .all()
    )
    return {r[0] for r in rows}


def get_new_candidate_ids(
    db: Session,
    job_id: str,
    owner_id: str,
    since: datetime,
) -> set[str]:
    """Candidatos asignados después de *since* (incremental mode)."""
    rows = (
        db.query(JobCandidate.candidate_id)
        .filter(
            JobCandidate.job_id == job_id,
            JobCandidate.owner_id == owner_id,
            JobCandidate.assigned_at > since,
        )
        .all()
    )
    return {r[0] for r in rows}


# ============================================================
# EVALUATIONS
# ============================================================

def get_evaluation(
    db: Session,
    job_id: str,
    candidate_id: str,
) -> Evaluation | None:
    return (
        db.query(Evaluation)
        .filter(
            Evaluation.job_id == job_id,
            Evaluation.candidate_id == candidate_id,
        )
        .first()
    )


def upsert_evaluation(
    db: Session,
    job_id: str,
    candidate_id: str,
    owner_id: str,
    *,
    job_title: str,
    job_description: str,
    candidate_name: str,
    match_score: int,
    recommendation: str,
    requirements: list,
    strengths: list,
    gaps: list,
    summary: str,
) -> Evaluation:
    existing = get_evaluation(db, job_id, candidate_id)

    now = datetime.now(timezone.utc)

    if existing:
        existing.job_title       = job_title
        existing.job_description = job_description
        existing.candidate_name  = candidate_name
        existing.match_score     = match_score
        existing.recommendation  = recommendation
        existing.requirements    = requirements
        existing.strengths       = strengths
        existing.gaps            = gaps
        existing.summary         = summary
        existing.evaluated_at    = now
        existing.status          = "COMPLETED"
        ev = existing
    else:
        ev = Evaluation(
            job_id=job_id,
            candidate_id=candidate_id,
            owner_id=owner_id,
            job_title=job_title,
            job_description=job_description,
            candidate_name=candidate_name,
            match_score=match_score,
            recommendation=recommendation,
            requirements=requirements,
            strengths=strengths,
            gaps=gaps,
            summary=summary,
            evaluated_at=now,
            status="COMPLETED",
        )
        db.add(ev)

    db.commit()
    db.refresh(ev)
    return ev


def get_evaluations_for_job(
    db: Session,
    job_id: str,
) -> list[Evaluation]:
    return (
        db.query(Evaluation)
        .filter(Evaluation.job_id == job_id)
        .order_by(Evaluation.match_score.desc())
        .all()
    )


# ============================================================
# RANKING
# ============================================================

def get_ranking_metadata(db: Session, job_id: str) -> Ranking | None:
    return (
        db.query(Ranking)
        .filter(Ranking.job_id == job_id)
        .first()
    )


def upsert_ranking_metadata(
    db: Session,
    job_id: str,
    version: int,
) -> Ranking:
    now = datetime.now(timezone.utc)
    existing = get_ranking_metadata(db, job_id)

    if existing:
        existing.ranking_generated_at = now
        existing.ranking_version      = version
    else:
        existing = Ranking(
            job_id=job_id,
            ranking_generated_at=now,
            ranking_version=version,
        )
        db.add(existing)

    db.commit()
    db.refresh(existing)
    return existing


def insert_ranking_items(
    db: Session,
    job_id: str,
    ranking_version: int,
    items: list[dict],
) -> int:
    """Bulk insert ranking snapshots.

    Each item dict must contain: candidate_id, candidate_name,
    match_score, recommendation, rank_position, strengths, gaps.
    """
    count = 0
    for item in items:
        db.add(
            RankingItem(
                job_id=job_id,
                candidate_id=item["candidate_id"],
                candidate_name=item["candidate_name"],
                match_score=item["match_score"],
                recommendation=item["recommendation"],
                rank_position=item["rank_position"],
                strengths=item["strengths"],
                gaps=item["gaps"],
                ranking_version=ranking_version,
            )
        )
        count += 1
    db.commit()
    return count


def get_ranking_items(
    db: Session,
    job_id: str,
    ranking_version: int,
) -> list[RankingItem]:
    return (
        db.query(RankingItem)
        .filter(
            RankingItem.job_id == job_id,
            RankingItem.ranking_version == ranking_version,
        )
        .order_by(RankingItem.rank_position)
        .all()
    )


# ============================================================
# RANKING — READ (consulta del endpoint GET /ranking)
# ============================================================

def get_ranking_for_job(
    db: Session,
    job_id: str,
    *,
    min_score: int = 0,
    max_score: int = 100,
    recommendation: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    """Build the full ranking response, including pending count.

    Returns a dict compatible with schemas.RankingMetadataResponse.
    """
    # 1. Metadata
    meta = get_ranking_metadata(db, job_id)

    # 2. All assigned candidates for this job
    assigned_ids = get_job_candidate_ids(db, job_id, owner_id="*")

    # If owner_id="*" is not used, caller should pass real owner.
    # Fallback: count via JobCandidate table directly.
    assigned_count = (
        db.query(func.count(JobCandidate.candidate_id))
        .filter(JobCandidate.job_id == job_id)
        .scalar()
    ) or 0

    # 3. Evaluations for this job
    query = (
        db.query(Evaluation)
        .filter(Evaluation.job_id == job_id)
    )

    # Filters
    query = query.filter(
        Evaluation.match_score >= min_score,
        Evaluation.match_score <= max_score,
    )
    if recommendation:
        query = query.filter(
            Evaluation.recommendation == recommendation
        )

    # Total (before pagination)
    total = query.count() or 0

    # Paginated results
    evaluations = (
        query
        .order_by(
            Evaluation.match_score.desc(),
            Evaluation.candidate_name,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    pending = max(0, assigned_count - total)

    candidates = []
    for idx, ev in enumerate(evaluations, start=(page - 1) * page_size + 1):
        candidates.append({
            "rank": idx,
            "candidate_id": ev.candidate_id,
            "candidate_name": ev.candidate_name,
            "match_score": ev.match_score,
            "recommendation": ev.recommendation,
            "strengths": ev.strengths or [],
            "gaps": ev.gaps or [],
        })

    return {
        "job_id": job_id,
        "job_title": (meta.job.title if meta and meta.job else ""),
        "ranking_generated_at": (
            meta.ranking_generated_at if meta else None
        ),
        "ranking_version": (meta.ranking_version if meta else None),
        "total": total,
        "total_pages": total_pages,
        "page": page,
        "page_size": page_size,
        "pending_candidates": pending,
        "candidates": candidates,
    }
