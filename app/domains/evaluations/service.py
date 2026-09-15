"""Evaluation service — orchestrates candidate-job evaluation use cases.

This module contains the business logic for evaluating a candidate against
a job description. It coordinates authorization, retrieval, LLM evaluation,
validation, and persistence while keeping HTTP concerns in the router.
"""

import logging

from sqlalchemy.orm import Session

from app.domains.candidates import service as candidates_service
from app.domains.candidates.exceptions import CandidateNotFound, JobNotFound
from app.domains.evaluations import repository as evaluations_repository
from app.domains.evaluations.rules import (
    normalize_completed_evaluation_result,
    validate_completed_evaluation_result,
)
from app.domains.jobs import repository as jobs_repository

logger = logging.getLogger(__name__)

FAILED_EVALUATION_PUBLIC_MESSAGE = (
    "No fue posible completar la evaluación. Intenta nuevamente."
)


def evaluate_candidate_for_owner(
    db: Session,
    *,
    candidate_id: str,
    job_id: str,
    owner_sub: str,
) -> tuple[object, bool, str | None]:
    """Authorize candidate/job visibility, then run the existing evaluation use case."""
    candidate = candidates_service.require_candidate(
        db,
        candidate_id,
        owner_sub,
    )
    job = jobs_repository.get_job(db, job_id, owner_sub=owner_sub)
    if job is None:
        raise JobNotFound(job_id)

    return evaluate_candidate_for_job(
        db,
        candidate=candidate,
        job=job,
    )


def evaluate_candidate_for_job(
    db: Session,
    *,
    candidate,
    job,
) -> tuple[object, bool, str | None]:
    """Evaluate a candidate for a specific job.

    Args:
        db: Database session
        candidate: Already-authorized Candidate domain object
        job: Already-authorized Job domain object

    Returns:
        tuple: (evaluation, newly_evaluated, internal_error)
        - evaluation: the persisted Evaluation object
        - newly_evaluated: True if this evaluation was just created/updated
        - internal_error: technical error message if any, None on success
    """
    # Import at execution time to allow monkeypatching in tests
    from app import evaluation as evaluation_backend

    retrieve_candidate = evaluation_backend.retrieve_candidate
    llm_evaluate = evaluation_backend.evaluate_candidate

    internal_error = None

    try:
        results = retrieve_candidate(
            candidate_id=candidate.id,
            question=job.description or job.title,
        )

        llm_result = llm_evaluate(
            candidate_id=candidate.id,
            job_description=job.description or job.title,
            results=results,
        )

        eval_status = llm_result.get("status", "COMPLETED")

        if eval_status == "FAILED":
            # LLM explicitly returned FAILED
            evaluation = evaluations_repository.create_evaluation(
                db,
                candidate_id=candidate.id,
                job_id=job.id,
                match_score=0.0,
                recommendation=llm_result.get("recommendation", "EVALUATION_FAILED"),
                summary=llm_result.get("summary", FAILED_EVALUATION_PUBLIC_MESSAGE),
                strengths=[],
                gaps=[],
                requirements=[],
                status="FAILED",
                error_message=llm_result.get("error_message", "EVALUATION_FAILED"),
            )
            return evaluation, True, None

        # Validate the supposedly completed result using canonical rules
        is_valid, error_msg = validate_completed_evaluation_result(llm_result)
        if not is_valid:
            raise ValueError(error_msg)

        # Normalize the validated result for persistence
        normalized = normalize_completed_evaluation_result(llm_result)

        evaluation = evaluations_repository.create_evaluation(
            db,
            candidate_id=candidate.id,
            job_id=job.id,
            match_score=normalized["match_score"],
            recommendation=normalized["recommendation"],
            summary=normalized["summary"],
            strengths=normalized["strengths"],
            gaps=normalized["gaps"],
            requirements=normalized["requirements"],
            status="COMPLETED",
            error_message=None,
        )
        return evaluation, True, None

    except Exception as exc:
        logger.error(
            "LLM evaluation failed for candidate %s: %s",
            candidate.id,
            exc,
            exc_info=True,
        )

        internal_error = str(exc)

        evaluation = evaluations_repository.create_evaluation(
            db,
            candidate_id=candidate.id,
            job_id=job.id,
            match_score=0.0,
            recommendation="EVALUATION_FAILED",
            summary=FAILED_EVALUATION_PUBLIC_MESSAGE,
            strengths=[],
            gaps=[],
            status="FAILED",
            error_message=internal_error,
        )
        return evaluation, True, internal_error
