"""Evaluation service — orchestrates candidate-job evaluation use case.

This module contains the business logic for evaluating a candidate against
a job description. It coordinates retrieval, LLM evaluation, validation,
and persistence.
"""

import logging
from sqlalchemy.orm import Session

from app.domains.evaluations import repository as evaluations_repository
from app.domains.evaluations.rules import validate_completed_evaluation_result

logger = logging.getLogger(__name__)

FAILED_EVALUATION_PUBLIC_MESSAGE = (
    "No fue posible completar la evaluación. Intenta nuevamente."
)


def evaluate_candidate_for_job(
    db: Session,
    *,
    candidate_id: str,
    job_id: str,
    job_description: str,
    owner_sub: str,
) -> tuple[object, bool, str | None]:
    """Evaluate a candidate for a specific job.

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
            candidate_id=candidate_id,
            question=job_description,
        )

        llm_result = llm_evaluate(
            candidate_id=candidate_id,
            job_description=job_description,
            results=results,
        )

        eval_status = llm_result.get("status", "COMPLETED")

        if eval_status == "FAILED":
            # LLM explicitly returned FAILED
            evaluation = evaluations_repository.create_evaluation(
                db,
                candidate_id=candidate_id,
                job_id=job_id,
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

        # Validate the supposedly completed result
        match_score = llm_result.get("match_score")
        recommendation = llm_result.get("recommendation")
        summary = str(llm_result.get("summary") or "").strip()
        strengths = llm_result.get("strengths", [])
        gaps = llm_result.get("gaps", [])
        requirements = llm_result.get("requirements", [])

        if not isinstance(requirements, list):
            raise ValueError("INVALID_EVALUATION_REQUIREMENTS")

        if match_score is None:
            raise ValueError("INVALID_EVALUATION_SCORE")

        try:
            numeric_score = float(match_score)
        except (TypeError, ValueError) as exc:
            raise ValueError("INVALID_EVALUATION_SCORE") from exc

        if not 0 <= numeric_score <= 100:
            raise ValueError("INVALID_EVALUATION_SCORE")

        valid_recommendations = {
            "STRONG_MATCH",
            "GOOD_MATCH",
            "PARTIAL_MATCH",
            "LOW_MATCH",
        }

        if recommendation not in valid_recommendations:
            raise ValueError("INVALID_EVALUATION_RECOMMENDATION")

        if len(summary) < evaluations_repository.MIN_SUMMARY_LENGTH:
            raise ValueError("INVALID_EVALUATION_SUMMARY")

        if not isinstance(strengths, list):
            raise ValueError("INVALID_EVALUATION_STRENGTHS")

        if not isinstance(gaps, list):
            raise ValueError("INVALID_EVALUATION_GAPS")

        evaluation = evaluations_repository.create_evaluation(
            db,
            candidate_id=candidate_id,
            job_id=job_id,
            match_score=numeric_score,
            recommendation=recommendation,
            summary=summary,
            strengths=strengths,
            gaps=gaps,
            requirements=requirements,
            status="COMPLETED",
            error_message=None,
        )
        return evaluation, True, None

    except Exception as exc:
        logger.error(
            "LLM evaluation failed for candidate %s: %s",
            candidate_id,
            exc,
            exc_info=True,
        )

        internal_error = str(exc)

        evaluation = evaluations_repository.create_evaluation(
            db,
            candidate_id=candidate_id,
            job_id=job_id,
            match_score=0.0,
            recommendation="EVALUATION_FAILED",
            summary=FAILED_EVALUATION_PUBLIC_MESSAGE,
            strengths=[],
            gaps=[],
            status="FAILED",
            error_message=internal_error,
        )
        return evaluation, True, internal_error