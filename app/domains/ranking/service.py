"""Ranking service — orchestrates full ranking recalculation use case.

This module contains the business logic for recalculating a job's ranking,
including lock management, candidate selection, evaluation orchestration,
and ranking persistence.
"""

import logging
from typing import Any
from sqlalchemy.orm import Session

from app.domains.jobs import repository as jobs_repository
from app.domains.candidates import repository as candidates_repository
from app.domains.evaluations import repository as evaluations_repository
from app.domains.ranking import repository as ranking_repository
from app.domains.ranking.exceptions import (
    RankingJobNotFound,
    RankingAlreadyRunning,
)
from app.deps import acquire_job_lock, release_job_lock
from app.domains.evaluations.service import evaluate_candidate_for_job

logger = logging.getLogger(__name__)

FAILED_EVALUATION_PUBLIC_MESSAGE = (
    "No fue posible completar la evaluación. Intenta nuevamente."
)

status_order = {
    "COMPLETED": 0,
    "FAILED": 1,
    "PENDING": 2,
}


def recalculate_ranking(
    db: Session,
    *,
    job_id: str,
    owner_sub: str,
    mode: str,
    scope: str,
) -> dict[str, Any]:
    """Recalculate the ranking for a job.

    Args:
        db: Database session
        job_id: Job identifier
        owner_sub: Owner Cognito subject
        mode: "full" or "incremental"
        scope: "assigned" or "all"

    Returns:
        dict with recalculation results including version, counts, and failures.

    Raises:
        RankingJobNotFound: if job not found or not accessible.
        RankingAlreadyRunning: if another recalculation is in progress.
    """
    # Verify job ownership
    job = jobs_repository.get_job(db, job_id, owner_sub=owner_sub)
    if not job:
        raise RankingJobNotFound()

    acquired = acquire_job_lock(db, job_id)

    if not acquired:
        raise RankingAlreadyRunning()

    try:
        meta = ranking_repository.get_ranking_metadata(db, job_id)

        prev_version = (meta.ranking_version if meta else 0) or 0
        new_version = prev_version + 1

        effective_mode = mode
        if mode == "incremental" and (not meta or not meta.generated_at):
            effective_mode = "full"

        ranking = ranking_repository.upsert_ranking_metadata(
            db,
            job_id,
            new_version,
            mode=effective_mode,
            scope=scope,
        )

        if scope == "all":
            ranking_candidates = candidates_repository.list_candidates(db, owner_sub=owner_sub)
        else:
            ranking_candidates, _ = candidates_repository.list_candidates_for_job(
                db,
                job_id,
                page=1,
                page_size=100000,
                owner_sub=owner_sub,
            )

        evaluated_count = 0
        failed_count = 0
        failures = []

        all_items: list[dict] = []

        for candidate in ranking_candidates:
            evaluation = evaluations_repository.get_evaluation_for_job_candidate(
                db,
                job_id,
                candidate.id,
            )

            if evaluations_repository.needs_evaluation(evaluation, force=(effective_mode == "full")):
                try:
                    # Use the shared evaluation service with authorized domain objects
                    evaluation, _, internal_error = evaluate_candidate_for_job(
                        db,
                        candidate=candidate,
                        job=job,
                    )

                    if evaluation.status == "FAILED":
                        failed_count += 1
                        error_msg = internal_error or evaluation.error_message or "EVALUATION_FAILED"
                        failures.append({"candidate_id": candidate.id, "error": error_msg})
                    else:
                        evaluated_count += 1

                except Exception as exc:
                    logger.error(
                        "Evaluation failed for candidate %s: %s",
                        candidate.id,
                        exc,
                        exc_info=True,
                    )

                    failed_count += 1
                    failures.append({"candidate_id": candidate.id, "error": str(exc)})

                    # Ensure FAILED evaluation is persisted
                    evaluation = evaluations_repository.create_evaluation(
                        db,
                        candidate_id=candidate.id,
                        job_id=job_id,
                        match_score=0.0,
                        recommendation="EVALUATION_FAILED",
                        summary=FAILED_EVALUATION_PUBLIC_MESSAGE,
                        strengths=[],
                        gaps=[],
                        status="FAILED",
                        error_message=str(exc),
                    )
            else:
                evaluated_count += 1

            # Determine effective status and score for ranking item
            if evaluations_repository.is_evaluation_complete(evaluation):
                effective_status = "COMPLETED"
                score = float(evaluation.match_score)
            elif evaluation and evaluation.status == "FAILED":
                effective_status = "FAILED"
                score = 0.0
            else:
                effective_status = "PENDING"
                score = 0.0

            all_items.append({
                "candidate_id": candidate.id,
                "candidate_name": candidate.name or "",
                "score": score,
                "status": effective_status,
            })

        # Sort items globally
        all_items.sort(
            key=lambda item: (
                status_order.get(item["status"], 99),
                -float(item["score"]),
                item["candidate_name"].lower(),
                item["candidate_id"],
            )
        )

        for position, item in enumerate(all_items, start=1):
            item["position"] = position

        # Persist ranking items (replaces any existing)
        if all_items:
            ranking_repository.insert_ranking_items(db, ranking_id=ranking.id, items=all_items)
        else:
            ranking_repository.insert_ranking_items(db, ranking_id=ranking.id, items=[])

        return {
            "job_id": job_id,
            "mode": effective_mode,
            "scope": scope,
            "total_candidates": len(ranking_candidates),
            "evaluated": evaluated_count,
            "failed": failed_count,
            "failures": failures,
            "ranking_version": new_version,
        }

    finally:
        release_job_lock(db, job_id)


def build_latest_ranking(
    db: Session,
    *,
    job_id: str,
    owner_sub: str,
) -> dict[str, Any]:
    """Build the latest ranking payload for a job.

    This extracts the logic from GET /{job_id}/ranking/latest endpoint.
    """
    from app.domains.ranking.exceptions import RankingJobNotFound, RankingNotFound

    job = jobs_repository.get_job(db, job_id, owner_sub=owner_sub)
    if not job:
        raise RankingJobNotFound()

    meta = ranking_repository.get_ranking_metadata(db, job_id)
    if not meta or meta.ranking_version == 0:
        raise RankingNotFound()

    items = ranking_repository.get_ranking_items(db, meta.id)

    candidates = []
    for item in items:
        evaluation = evaluations_repository.get_evaluation_for_job_candidate(db, job_id, item.candidate_id)

        if evaluations_repository.is_evaluation_complete(evaluation):
            candidates.append({
                "position": item.position,
                "candidate_id": item.candidate_id,
                "match_score": evaluation.match_score,
                "candidate_name": item.candidate.name if item.candidate else "",
                "recommendation": evaluation.recommendation,
                "status": "COMPLETED",
                "strengths": evaluation.strengths or [],
                "gaps": evaluation.gaps or [],
                "error_message": None,
            })
        elif evaluation and evaluation.status == "FAILED":
            candidates.append({
                "position": item.position,
                "candidate_id": item.candidate_id,
                "match_score": None,
                "candidate_name": item.candidate.name if item.candidate else "",
                "recommendation": "EVALUATION_FAILED",
                "status": "FAILED",
                "strengths": [],
                "gaps": [],
                "error_message": ranking_repository._sanitize_error_message(evaluation.error_message) or "Evaluacion fallida",
            })
        else:
            candidates.append({
                "position": item.position,
                "candidate_id": item.candidate_id,
                "match_score": None,
                "candidate_name": item.candidate.name if item.candidate else "",
                "recommendation": "PENDING",
                "status": "PENDING",
                "strengths": [],
                "gaps": [],
                "error_message": "Evaluacion pendiente",
            })

    return {
        "job_id": job_id,
        "job_title": job.title,
        "ranking_generated_at": meta.generated_at.isoformat() if meta.generated_at else None,
        "ranking_version": meta.ranking_version,
        "total": len(items),
        "total_pages": 1,
        "page": 1,
        "page_size": len(items),
        "pending_candidates": 0,
        "candidates": candidates,
    }