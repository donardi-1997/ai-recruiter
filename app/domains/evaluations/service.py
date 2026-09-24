"""Evaluation service — orchestrates candidate-job evaluation use cases.

This module contains the business logic for evaluating a candidate against
a job description. It coordinates authorization, retrieval, LLM evaluation,
validation, and persistence while keeping HTTP concerns in the router.
"""

import logging

from sqlalchemy.orm import Session

from app.domains.candidates import service as candidates_service
from app.domains.candidates.exceptions import CandidateBanned, CandidateNotFound, JobNotFound
from app.domains.evaluations import repository as evaluations_repository
from app.domains.evaluations.rules import (
    normalize_completed_evaluation_result,
    validate_completed_evaluation_result,
)
from app.domains.jobs import repository as jobs_repository
from app.domains.jobs.profile import build_evaluation_text, has_evaluation_criteria

logger = logging.getLogger(__name__)

FAILED_EVALUATION_PUBLIC_MESSAGE = (
    "No fue posible completar la evaluación. Intenta nuevamente."
)
INTERNAL_EVALUATION_ERROR_CODE = "EVALUATION_INTERNAL_ERROR"


class EvaluationCriteriaMissing(RuntimeError):
    """Raised when a vacancy has no recruiter-authored criteria to compare."""


def _safe_failure_code(value: object) -> str:
    candidate = str(value or "").strip()
    if (
        3 <= len(candidate) <= 120
        and all(character.isupper() or character.isdigit() or character == "_" for character in candidate)
    ):
        return candidate
    return "EVALUATION_FAILED"


def evaluate_candidate_for_owner(
    db: Session,
    *,
    candidate_id: str,
    job_id: str,
    owner_sub: str,
    force: bool = False,
) -> tuple[object, bool, str | None]:
    """Authorize candidate/job visibility, then run the evaluation use case."""
    candidate = candidates_service.require_candidate(
        db,
        candidate_id,
        owner_sub,
    )
    if getattr(candidate, "is_banned", False):
        raise CandidateBanned(candidate_id)

    job = jobs_repository.get_job(db, job_id, owner_sub=owner_sub)
    if job is None:
        raise JobNotFound(job_id)
    if not has_evaluation_criteria(job):
        raise EvaluationCriteriaMissing("JOB_EVALUATION_CRITERIA_MISSING")

    if force:
        return evaluate_candidate_for_job(
            db,
            candidate=candidate,
            job=job,
            force=True,
        )
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
    force: bool = False,
) -> tuple[object, bool, str | None]:
    """Evaluate a candidate for a specific job only when the result is stale.

    A complete evaluation produced from the current ``job.evaluation_version``
    is returned directly. This freshness check is centralized here so manual
    evaluation, imports, Gmail ingestion, Indeed ingestion, and reevaluation
    workers all share the same no-op behavior for unchanged vacancies.
    """
    current_job_version = int(getattr(job, "evaluation_version", 1) or 1)
    existing = evaluations_repository.get_evaluation_for_job_candidate(
        db,
        job.id,
        candidate.id,
    )
    if not evaluations_repository.needs_evaluation(
        existing,
        current_job_version=current_job_version,
        force=force,
    ):
        return existing, False, None

    # Import at execution time to allow monkeypatching in tests.
    from app import evaluation as evaluation_backend

    retrieve_candidate = evaluation_backend.retrieve_candidate
    llm_evaluate = evaluation_backend.evaluate_candidate
    evaluation_text = build_evaluation_text(job)

    internal_error = None

    try:
        results = retrieve_candidate(
            candidate_id=candidate.id,
            question=evaluation_text,
        )

        llm_result = llm_evaluate(
            candidate_id=candidate.id,
            job_description=evaluation_text,
            results=results,
        )

        eval_status = llm_result.get("status", "COMPLETED")

        if eval_status == "FAILED":
            evaluation = evaluations_repository.create_evaluation(
                db,
                candidate_id=candidate.id,
                job_id=job.id,
                job_evaluation_version=current_job_version,
                match_score=0.0,
                recommendation=llm_result.get("recommendation", "EVALUATION_FAILED"),
                summary=llm_result.get("summary", FAILED_EVALUATION_PUBLIC_MESSAGE),
                strengths=[],
                gaps=[],
                requirements=[],
                status="FAILED",
                error_message=_safe_failure_code(
                    llm_result.get("error_message", "EVALUATION_FAILED")
                ),
            )
            return evaluation, True, None

        is_valid, error_msg = validate_completed_evaluation_result(llm_result)
        if not is_valid:
            raise ValueError(error_msg)

        normalized = normalize_completed_evaluation_result(llm_result)

        evaluation = evaluations_repository.create_evaluation(
            db,
            candidate_id=candidate.id,
            job_id=job.id,
            job_evaluation_version=current_job_version,
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
            job_evaluation_version=current_job_version,
            match_score=0.0,
            recommendation="EVALUATION_FAILED",
            summary=FAILED_EVALUATION_PUBLIC_MESSAGE,
            strengths=[],
            gaps=[],
            requirements=[],
            status="FAILED",
            error_message=INTERNAL_EVALUATION_ERROR_CODE,
        )
        return evaluation, True, internal_error