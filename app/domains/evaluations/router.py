"""Evaluations router — FastAPI endpoints for candidate evaluations."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_db, require_permission
from app.domains.evaluations.presenter import public_evaluation_payload
from app.domains.evaluations.schemas import EvaluateRequest
from app.domains.evaluations.service import (
    CandidateBanned,
    CandidateNotFound,
    EvaluationCriteriaMissing,
    JobNotFound,
    evaluate_candidate_for_owner,
)

router = APIRouter(prefix="/api/candidates", tags=["evaluations"])


@router.post("/{candidate_id}/evaluate-job")
def evaluate_candidate_endpoint(
    candidate_id: str,
    body: EvaluateRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("candidates.evaluate")),
):
    try:
        evaluation, _, _ = evaluate_candidate_for_owner(
            db,
            candidate_id=candidate_id,
            job_id=body.job_id,
            owner_sub=_user["sub"],
        )
    except CandidateNotFound as exc:
        raise HTTPException(status_code=404, detail="Candidato no encontrado.") from exc
    except CandidateBanned as exc:
        raise HTTPException(
            status_code=409,
            detail="El candidato está vetado. Quita el veto antes de evaluarlo.",
        ) from exc
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.") from exc
    except EvaluationCriteriaMissing as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "La vacante no tiene descripción ni criterios de evaluación. "
                "Complétala o usa 'Enriquecer con IA' en Vacantes antes de evaluar."
            ),
        ) from exc

    return public_evaluation_payload(evaluation)
