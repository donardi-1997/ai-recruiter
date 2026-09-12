"""Evaluations router — FastAPI endpoints for candidate evaluations."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.domains.evaluations.presenter import public_evaluation_payload
from app.domains.evaluations.schemas import EvaluateRequest
from app.domains.evaluations.service import (
    CandidateNotFound,
    JobNotFound,
    evaluate_candidate_for_owner,
)

router = APIRouter(prefix="/api/candidates", tags=["evaluations"])


@router.post("/{candidate_id}/evaluate-job")
def evaluate_candidate_endpoint(
    candidate_id: str,
    body: EvaluateRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
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
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.") from exc

    return public_evaluation_payload(evaluation)
