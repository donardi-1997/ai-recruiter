"""CRUD operations — transaction management and advisory locks."""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Candidate, Job, Ranking, RankingItem

logger = logging.getLogger(__name__)


# ============================================================
# SCORING SKELETON
# ============================================================

def compute_score_for_candidate(candidate: Candidate) -> float:
    """Compute an affinity score for *candidate*.

    Skeleton — replace with your ML model / Bedrock evaluator.
    Returns a placeholder score between 0.0 and 100.0.
    """
    # TODO: integrate your ML model here
    return 0.0


# ============================================================
# JOBS
# ============================================================

def get_job(db: Session, job_id: str) -> Job | None:
    return db.query(Job).filter(Job.id == job_id).first()


# ============================================================
# CANDIDATES
# ============================================================

def get_candidate(db: Session, candidate_id: str) -> Candidate | None:
    return db.query(Candidate).filter(Candidate.id == candidate_id).first()


def list_candidates_for_job(
    db: Session,
    job_id: str,
    *,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[Candidate], int]:
    """List candidates that have ranking items for a given job."""
    from app.models import RankingItem

    query = (
        db.query(Candidate)
        .join(RankingItem, RankingItem.candidate_id == Candidate.id)
        .join(Ranking, Ranking.id == RankingItem.ranking_id)
        .filter(Ranking.job_id == job_id)
        .distinct()
        .order_by(Candidate.name)
    )
    total = query.count() or 0
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, total


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
    """Bulk insert ranking items atomically.

    Each *items* dict must contain: candidate_id, score, position.
    """
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
    """Build ranking response — empty if no ranking exists."""
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
