"""Evaluations router — FastAPI endpoints for candidate evaluations."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app import crud
from app.domains.evaluations.schemas import EvaluateRequest
from app.domains.evaluations.service import evaluate_candidate_for_job
from app.domains.evaluations.presenter import public_evaluation_payload

router = APIRouter(prefix="/api/candidates", tags=["evaluations"])


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


@router.post("/{candidate_id}/evaluate-job")
def evaluate_candidate_endpoint(
    candidate_id: str,
    body: EvaluateRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    candidate = _require_candidate(db, candidate_id, _user["sub"])
    job = _require_job(db, body.job_id, _user["sub"])

    evaluation, _, _ = evaluate_candidate_for_job(
        db,
        candidate=candidate,
        job=job,
    )

    return public_evaluation_payload(evaluation)