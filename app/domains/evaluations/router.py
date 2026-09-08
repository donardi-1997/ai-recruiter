"""Evaluations router."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app import crud
from app.domains.evaluations.schemas import EvaluateRequest

router = APIRouter(prefix="/api/candidates", tags=["evaluations"])

FAILED_EVALUATION_PUBLIC_MESSAGE = (
    "No fue posible completar la evaluación. Intenta nuevamente."
)


def _require_candidate(db: Session, candidate_id: str, owner_sub: str):
    candidate = crud.get_candidate(db, candidate_id, owner_sub=owner_sub)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidato no encontrado.")
    return candidate


def _require_job(db: Session, job_id: str, owner_sub: str):
    job = crud.get_job(db, job_id, owner_sub=owner_sub)
    if not job:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")
    return job


def _public_evaluation_payload(evaluation):
    """Serialize an Evaluation without exposing technical failure details."""
    failed = evaluation.status == "FAILED"

    return {
        "evaluation_id": evaluation.id,
        "candidate_id": evaluation.candidate_id,
        "job_id": evaluation.job_id,
        "status": evaluation.status,
        "match_score": None if failed else evaluation.match_score,
        "recommendation": (
            "EVALUATION_FAILED"
            if failed
            else evaluation.recommendation
        ),
        "summary": (
            FAILED_EVALUATION_PUBLIC_MESSAGE
            if failed
            else (evaluation.summary or "")
        ),
        "strengths": [] if failed else (evaluation.strengths or []),
        "gaps": [] if failed else (evaluation.gaps or []),
        "requirements": (
            []
            if failed
            else (evaluation.requirements or [])
        ),
        "error_message": (
            FAILED_EVALUATION_PUBLIC_MESSAGE
            if failed
            else None
        ),
    }


@router.post("/{candidate_id}/evaluate-job")
def evaluate_candidate_for_job(
    candidate_id: str,
    body: EvaluateRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    from app.evaluation import evaluate_candidate as llm_evaluate, retrieve_candidate

    candidate = _require_candidate(db, candidate_id, _user["sub"])
    job = _require_job(db, body.job_id, _user["sub"])

    try:
        results = retrieve_candidate(
            candidate_id=candidate_id,
            question=job.description or job.title,
        )

        llm_result = llm_evaluate(
            candidate_id=candidate_id,
            job_description=job.description or job.title,
            results=results,
        )

        eval_status = llm_result.get("status", "COMPLETED")

        if eval_status == "FAILED":
            evaluation = crud.create_evaluation(
                db,
                candidate_id=candidate_id,
                job_id=body.job_id,
                match_score=0.0,
                recommendation=llm_result.get("recommendation", "EVALUATION_FAILED"),
                summary=llm_result.get("summary", FAILED_EVALUATION_PUBLIC_MESSAGE),
                strengths=[],
                gaps=[],
                requirements=[],
                status="FAILED",
                error_message=llm_result.get("error_message", "EVALUATION_FAILED"),
            )
        else:
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

            if len(summary) < crud.MIN_SUMMARY_LENGTH:
                raise ValueError("INVALID_EVALUATION_SUMMARY")

            if not isinstance(strengths, list):
                raise ValueError("INVALID_EVALUATION_STRENGTHS")

            if not isinstance(gaps, list):
                raise ValueError("INVALID_EVALUATION_GAPS")

            evaluation = crud.create_evaluation(
                db,
                candidate_id=candidate_id,
                job_id=body.job_id,
                match_score=numeric_score,
                recommendation=recommendation,
                summary=summary,
                strengths=strengths,
                gaps=gaps,
                requirements=requirements,
                status="COMPLETED",
                error_message=None,
            )

    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(
            "LLM evaluation failed for candidate %s: %s",
            candidate_id,
            exc,
            exc_info=True,
        )

        evaluation = crud.create_evaluation(
            db,
            candidate_id=candidate_id,
            job_id=body.job_id,
            match_score=0.0,
            recommendation="EVALUATION_FAILED",
            summary=FAILED_EVALUATION_PUBLIC_MESSAGE,
            strengths=[],
            gaps=[],
            status="FAILED",
            error_message=str(exc),
        )

    return _public_evaluation_payload(evaluation)