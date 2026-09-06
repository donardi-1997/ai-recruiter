"""CRUD operations — transaction management and advisory locks."""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models import Candidate, Evaluation, Job, JobCandidate, Ranking, RankingItem

logger = logging.getLogger(__name__)


def _sanitize_error_message(error_message: str | None) -> str | None:
    """Sanitize error messages for public API consumption.

    Technical AWS details (ARNs, account IDs, exception names) are preserved
    internally but replaced with user-friendly messages in API responses.
    """
    if not error_message:
        return None

    # If it contains AWS technical details, return generic message
    aws_indicators = [
        "AccessDeniedException",
        "arn:aws",
        "assumed-role",
        "AmazonLightsailInstanceRole",
        "knowledge-base/",
        "bedrock:Retrieve",
        "bedrock:InvokeModel",
        "is not authorized to perform",
    ]
    for indicator in aws_indicators:
        if indicator in error_message:
            return "No fue posible completar la evaluación. Intente recalcular el ranking."

    return error_message


# ============================================================
# JOBS
# ============================================================

def get_job(
    db: Session,
    job_id: str,
    owner_sub: str | None = None,
) -> Job | None:
    query = db.query(Job).filter(Job.id == job_id)

    if owner_sub is not None:
        query = query.filter(
            Job.owner_sub == owner_sub
        )

    return query.first()


def list_jobs(
    db: Session,
    owner_sub: str | None = None,
) -> list[Job]:
    query = db.query(Job)

    if owner_sub is not None:
        query = query.filter(
            Job.owner_sub == owner_sub
        )

    return query.order_by(
        Job.created_at.desc()
    ).all()


def create_job(
    db: Session,
    *,
    title: str,
    description: str | None = None,
    owner_sub: str | None = None,
) -> Job:
    job = Job(
        title=title,
        description=description,
        owner_sub=owner_sub,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_job(db: Session, job: Job, *, title: str | None = None, description: str | None = None) -> Job:
    if title is not None:
        job.title = title
    if description is not None:
        job.description = description
    db.commit()
    db.refresh(job)
    return job


def delete_job(
    db: Session,
    job_id: str,
    *,
    owner_sub: str | None = None,
    delete_candidates: bool = False,
) -> tuple[bool, int]:
    """Delete a job and its related records atomically.

    When *delete_candidates* is True, every candidate currently assigned
    to the job is also removed (including their evaluations and ranking
    items across **all** jobs).  Shared candidates disappear from every
    job they belong to.

    Returns (success, deleted_candidates_count).
    """
    job = get_job(db, job_id, owner_sub=owner_sub)
    if not job:
        return False, 0

    try:
        # Collect candidate IDs assigned to this job
        # (only those owned by the current user).
        candidate_query = (
            db.query(JobCandidate.candidate_id)
            .filter(JobCandidate.job_id == job_id)
        )
        if owner_sub is not None:
            candidate_query = candidate_query.join(
                Candidate,
                Candidate.id == JobCandidate.candidate_id,
            ).filter(Candidate.owner_sub == owner_sub)

        candidate_ids = [
            cid for (cid,) in candidate_query.all()
        ]

        deleted_candidate_count = 0

        if delete_candidates and candidate_ids:
            # Remove associations and evaluations for
            # these candidates across ALL jobs.
            db.query(JobCandidate).filter(
                JobCandidate.candidate_id.in_(candidate_ids)
            ).delete(synchronize_session=False)

            db.query(Evaluation).filter(
                Evaluation.candidate_id.in_(candidate_ids)
            ).delete(synchronize_session=False)

            db.query(RankingItem).filter(
                RankingItem.candidate_id.in_(candidate_ids)
            ).delete(synchronize_session=False)

            db.query(Candidate).filter(
                Candidate.id.in_(candidate_ids)
            ).delete(synchronize_session=False)

            deleted_candidate_count = len(candidate_ids)

        # Remove job-linked records.
        ranking_ids = [
            rid
            for (rid,) in (
                db.query(Ranking.id)
                .filter(Ranking.job_id == job_id)
                .all()
            )
        ]

        if ranking_ids:
            db.query(RankingItem).filter(
                RankingItem.ranking_id.in_(ranking_ids)
            ).delete(synchronize_session=False)

        db.query(Ranking).filter(
            Ranking.job_id == job_id
        ).delete(synchronize_session=False)

        db.query(Evaluation).filter(
            Evaluation.job_id == job_id
        ).delete(synchronize_session=False)

        db.query(JobCandidate).filter(
            JobCandidate.job_id == job_id
        ).delete(synchronize_session=False)

        db.delete(job)
        db.commit()
        return True, deleted_candidate_count

    except Exception:
        db.rollback()
        raise


def count_candidates_for_job(
    db: Session,
    job_id: str,
    owner_sub: str | None = None,
) -> int:
    query = (
        db.query(JobCandidate)
        .join(
            Candidate,
            Candidate.id
            == JobCandidate.candidate_id,
        )
        .filter(
            JobCandidate.job_id == job_id
        )
    )

    if owner_sub is not None:
        query = query.filter(
            Candidate.owner_sub == owner_sub
        )

    return query.count()


def get_candidate(
    db: Session,
    candidate_id: str,
    owner_sub: str | None = None,
) -> Candidate | None:
    query = db.query(Candidate).filter(
        Candidate.id == candidate_id
    )

    if owner_sub is not None:
        query = query.filter(
            Candidate.owner_sub == owner_sub
        )

    return query.first()


def list_candidates(
    db: Session,
    owner_sub: str | None = None,
) -> list[Candidate]:
    query = db.query(Candidate)

    if owner_sub is not None:
        query = query.filter(
            Candidate.owner_sub == owner_sub
        )

    return query.order_by(
        Candidate.created_at.desc()
    ).all()


def create_candidate(
    db: Session,
    *,
    name: str,
    email: str | None = None,
    metadata: dict | None = None,
    owner_sub: str | None = None,
) -> Candidate:
    candidate = Candidate(
        name=name,
        email=email,
        metadata_=metadata or {},
        owner_sub=owner_sub,
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


def delete_candidate(db: Session, candidate_id: str) -> bool:
    candidate = get_candidate(db, candidate_id)
    if not candidate:
        return False
    # Delete related records first to avoid FK constraint violations
    db.query(JobCandidate).filter(JobCandidate.candidate_id == candidate_id).delete()
    db.query(Evaluation).filter(Evaluation.candidate_id == candidate_id).delete()
    db.query(RankingItem).filter(RankingItem.candidate_id == candidate_id).delete()
    db.delete(candidate)
    db.commit()
    return True


def delete_all_candidates(
    db: Session,
    owner_sub: str | None = None,
) -> tuple[int, int]:
    query = db.query(Candidate)

    if owner_sub is not None:
        query = query.filter(
            Candidate.owner_sub == owner_sub
        )

    candidate_ids = [
        candidate_id
        for (candidate_id,) in query.with_entities(
            Candidate.id
        ).all()
    ]

    count = len(candidate_ids)

    if not candidate_ids:
        return 0, 0

    db.query(JobCandidate).filter(
        JobCandidate.candidate_id.in_(
            candidate_ids
        )
    ).delete(
        synchronize_session=False
    )

    db.query(Evaluation).filter(
        Evaluation.candidate_id.in_(
            candidate_ids
        )
    ).delete(
        synchronize_session=False
    )

    db.query(RankingItem).filter(
        RankingItem.candidate_id.in_(
            candidate_ids
        )
    ).delete(
        synchronize_session=False
    )

    db.query(Candidate).filter(
        Candidate.id.in_(candidate_ids)
    ).delete(
        synchronize_session=False
    )

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
    query = (
        db.query(Candidate)
        .join(
            JobCandidate,
            JobCandidate.candidate_id
            == Candidate.id,
        )
        .filter(
            JobCandidate.job_id == job_id
        )
    )

    if owner_sub is not None:
        query = query.filter(
            Candidate.owner_sub == owner_sub
        )

    query = query.order_by(
        Candidate.name
    )

    total = query.count() or 0

    items = (
        query
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return items, total


def assign_candidates_to_job(
    db: Session,
    job_id: str,
    candidate_ids: list[str],
    owner_sub: str | None = None,
) -> tuple[int, int]:
    assigned = 0
    skipped = 0

    candidate_query = db.query(
        Candidate.id
    ).filter(
        Candidate.id.in_(candidate_ids)
    )

    if owner_sub is not None:
        candidate_query = candidate_query.filter(
            Candidate.owner_sub == owner_sub
        )

    allowed_ids = {
        candidate_id
        for (candidate_id,)
        in candidate_query.all()
    }

    for cid in candidate_ids:
        # Never allow assignment of a candidate
        # owned by a different Cognito user.
        if cid not in allowed_ids:
            skipped += 1
            continue

        existing = (
            db.query(JobCandidate)
            .filter(
                JobCandidate.job_id == job_id,
                JobCandidate.candidate_id == cid,
            )
            .first()
        )

        if existing:
            skipped += 1
            continue

        db.add(
            JobCandidate(
                job_id=job_id,
                candidate_id=cid,
            )
        )
        assigned += 1

    db.commit()
    return assigned, skipped


# ============================================================
# EVALUATION CONTRACT
# ============================================================

VALID_RECOMMENDATIONS = {
    "STRONG_MATCH",
    "GOOD_MATCH",
    "PARTIAL_MATCH",
    "LOW_MATCH",
    "EVALUATION_FAILED",
    "PENDING",
}

MIN_SUMMARY_LENGTH = 100

def is_evaluation_complete(evaluation: Evaluation | None) -> bool:
    """Check if an evaluation is complete and valid.

    An evaluation is complete ONLY if ALL of:
    - evaluation exists
    - status == "COMPLETED"
    - match_score is not None
    - 0 <= match_score <= 100
    - recommendation is a valid non-empty string
    - summary is a non-empty string with at least MIN_SUMMARY_LENGTH characters
    - strengths is a list (can be empty)
    - gaps is a list (can be empty)

    FAILED evaluations, None evaluations, and incomplete evaluations
    all return False.
    """
    if evaluation is None:
        return False
    if evaluation.status != "COMPLETED":
        return False
    if evaluation.match_score is None:
        return False
    if not (0 <= evaluation.match_score <= 100):
        return False
    if not evaluation.recommendation:
        return False
    if evaluation.recommendation not in VALID_RECOMMENDATIONS:
        return False
    if evaluation.recommendation == "EVALUATION_FAILED":
        return False
    if not evaluation.summary:
        return False
    if len(evaluation.summary.strip()) < MIN_SUMMARY_LENGTH:
        return False
    if evaluation.strengths is None:
        return False
    if evaluation.gaps is None:
        return False
    return True


def needs_evaluation(
    evaluation: Evaluation | None,
    *,
    force: bool = False,
) -> bool:
    """Determine if a candidate needs (re-)evaluation.

    Returns True if:
    - No evaluation exists
    - force=True (full mode)
    - Evaluation is FAILED
    - Evaluation is incomplete (missing recommendation, score, etc.)
    """
    if force:
        return True
    if evaluation is None:
        return True
    if evaluation.status == "FAILED":
        return True
    if evaluation.recommendation == "EVALUATION_FAILED":
        return True
    if not is_evaluation_complete(evaluation):
        return True
    return False


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
    requirements: list[dict] | None = None,
    status: str = "COMPLETED",
    error_message: str | None = None,
) -> Evaluation:
    # Upsert: one current evaluation for a
    # candidate/job pair.
    existing = get_evaluation_for_job_candidate(
        db,
        job_id,
        candidate_id,
    )

    if existing:
        existing.status = status
        existing.match_score = match_score
        existing.recommendation = recommendation
        existing.summary = summary
        existing.strengths = strengths
        existing.gaps = gaps

        if requirements is not None:
            existing.requirements = requirements

        existing.error_message = error_message
        existing.created_at = datetime.now(
            timezone.utc
        )

        db.commit()
        db.refresh(existing)
        return existing

    evaluation = Evaluation(
        candidate_id=candidate_id,
        job_id=job_id,
        status=status,
        match_score=match_score,
        recommendation=recommendation,
        summary=summary,
        strengths=strengths,
        gaps=gaps,
        requirements=requirements or [],
        error_message=error_message,
    )

    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)

    return evaluation


def get_evaluations_for_candidate(db: Session, candidate_id: str) -> list[Evaluation]:
    return db.query(Evaluation).filter(Evaluation.candidate_id == candidate_id).order_by(Evaluation.created_at.desc()).all()


def get_evaluation_for_job_candidate(db: Session, job_id: str, candidate_id: str) -> Evaluation | None:
    return (
        db.query(Evaluation)
        .filter(Evaluation.job_id == job_id, Evaluation.candidate_id == candidate_id)
        .order_by(Evaluation.created_at.desc())
        .first()
    )


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
    scope: str = "assigned",
) -> Ranking:
    now = datetime.now(timezone.utc)

    existing = get_ranking_metadata(db, job_id)

    if existing:
        existing.generated_at = now
        existing.ranking_version = version
        existing.mode = mode
        existing.notes = f"scope:{scope}"
    else:
        existing = Ranking(
            job_id=job_id,
            ranking_version=version,
            generated_at=now,
            mode=mode,
            notes=f"scope:{scope}",
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
    # Delete old items for this ranking first
    db.query(RankingItem).filter(RankingItem.ranking_id == ranking_id).delete()
    db.flush()

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
    min_score: float = 0,
    max_score: float = 100,
    recommendation: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """Return the current ranking sorted and paginated correctly.

    Sorting is global and deterministic:
    COMPLETED first, highest score first, then candidate name.
    FAILED and PENDING are placed after valid evaluations.

    Filtering happens before pagination.
    """

    job = get_job(db, job_id)
    meta = get_ranking_metadata(db, job_id)

    if not meta:
        requested_scope = scope or "assigned"

        return {
            "job_id": job_id,
            "job_title": job.title if job else "",
            "ranking_generated_at": None,
            "ranking_version": None,
            "ranking_scope": requested_scope,
            "scope_mismatch": False,
            "ranking_total": 0,
            "total": 0,
            "total_pages": 0,
            "page": page,
            "page_size": page_size,
            "pending_candidates": 0,
            "score_min": None,
            "score_max": None,
            "candidates": [],
        }

    ranking_scope = "assigned"

    if meta.notes and meta.notes.startswith("scope:"):
        candidate_scope = meta.notes.split(":", 1)[1].strip()

        if candidate_scope in {"assigned", "all"}:
            ranking_scope = candidate_scope

    # A ranking generated for "all" must never be silently returned
    # as though it belonged to "assigned", and vice versa.
    if scope is not None and scope != ranking_scope:
        return {
            "job_id": job_id,
            "job_title": job.title if job else "",
            "ranking_generated_at": (
                meta.generated_at.isoformat()
                if meta.generated_at
                else None
            ),
            "ranking_version": meta.ranking_version,
            "ranking_scope": ranking_scope,
            "scope_mismatch": True,
            "ranking_total": 0,
            "total": 0,
            "total_pages": 0,
            "page": page,
            "page_size": page_size,
            "pending_candidates": 0,
            "score_min": None,
            "score_max": None,
            "candidates": [],
        }

    items = (
        db.query(RankingItem)
        .options(joinedload(RankingItem.candidate))
        .filter(RankingItem.ranking_id == meta.id)
        .all()
    )

    candidate_ids = [
        item.candidate_id
        for item in items
    ]

    latest_evaluation_by_candidate = {}

    if candidate_ids:
        evaluations = (
            db.query(Evaluation)
            .filter(
                Evaluation.job_id == job_id,
                Evaluation.candidate_id.in_(candidate_ids),
            )
            .order_by(Evaluation.created_at.desc())
            .all()
        )

        for evaluation in evaluations:
            latest_evaluation_by_candidate.setdefault(
                evaluation.candidate_id,
                evaluation,
            )

    candidates = []

    for item in items:
        evaluation = latest_evaluation_by_candidate.get(
            item.candidate_id
        )

        candidate_name = (
            item.candidate.name
            if item.candidate
            else ""
        )

        if is_evaluation_complete(evaluation):
            candidates.append({
                "position": 0,
                "candidate_id": item.candidate_id,
                "match_score": evaluation.match_score,
                "candidate_name": candidate_name,
                "recommendation": evaluation.recommendation,
                "status": "COMPLETED",
                "strengths": evaluation.strengths or [],
                "gaps": evaluation.gaps or [],
                "error_message": None,
            })

        elif evaluation and evaluation.status == "FAILED":
            candidates.append({
                "position": 0,
                "candidate_id": item.candidate_id,
                "match_score": None,
                "candidate_name": candidate_name,
                "recommendation": "EVALUATION_FAILED",
                "status": "FAILED",
                "strengths": [],
                "gaps": [],
                "error_message": (
                    _sanitize_error_message(
                        evaluation.error_message
                    )
                    or "Evaluacion fallida"
                ),
            })

        else:
            candidates.append({
                "position": 0,
                "candidate_id": item.candidate_id,
                "match_score": None,
                "candidate_name": candidate_name,
                "recommendation": "PENDING",
                "status": "PENDING",
                "strengths": [],
                "gaps": [],
                "error_message": "Evaluacion pendiente",
            })

    status_order = {
        "COMPLETED": 0,
        "FAILED": 1,
        "PENDING": 2,
    }

    def sort_key(candidate):
        score = candidate.get("match_score")

        numeric_score = (
            float(score)
            if score is not None
            else -1.0
        )

        return (
            status_order.get(
                candidate.get("status"),
                99,
            ),
            -numeric_score,
            (candidate.get("candidate_name") or "").lower(),
            candidate.get("candidate_id") or "",
        )

    # Highest score first.
    candidates.sort(key=sort_key)

    # Position belongs to the complete ranking,
    # not to the current page.
    for position, candidate in enumerate(
        candidates,
        start=1,
    ):
        candidate["position"] = position

    ranking_total = len(candidates)

    filtered = candidates

    if recommendation:
        filtered = [
            candidate
            for candidate in filtered
            if candidate.get("recommendation")
            == recommendation
        ]

    # When score filtering is active, rows without a valid
    # score do not belong in the filtered score result.
    if min_score > 0 or max_score < 100:
        filtered = [
            candidate
            for candidate in filtered
            if (
                candidate.get("status") == "COMPLETED"
                and candidate.get("match_score") is not None
                and min_score
                <= float(candidate["match_score"])
                <= max_score
            )
        ]

    total = len(filtered)

    total_pages = (
        (total + page_size - 1) // page_size
        if total > 0
        else 0
    )

    start = (page - 1) * page_size
    end = start + page_size

    page_candidates = filtered[start:end]

    completed_scores = [
        float(candidate["match_score"])
        for candidate in filtered
        if (
            candidate.get("status") == "COMPLETED"
            and candidate.get("match_score") is not None
        )
    ]

    pending_candidates = sum(
        1
        for candidate in filtered
        if candidate.get("status") == "PENDING"
    )

    return {
        "job_id": job_id,
        "job_title": job.title if job else "",
        "ranking_generated_at": (
            meta.generated_at.isoformat()
            if meta.generated_at
            else None
        ),
        "ranking_version": meta.ranking_version,
        "ranking_scope": ranking_scope,
        "scope_mismatch": False,
        "ranking_total": ranking_total,
        "total": total,
        "total_pages": total_pages,
        "page": page,
        "page_size": page_size,
        "pending_candidates": pending_candidates,
        "score_min": (
            min(completed_scores)
            if completed_scores
            else None
        ),
        "score_max": (
            max(completed_scores)
            if completed_scores
            else None
        ),
        "candidates": page_candidates,
    }
