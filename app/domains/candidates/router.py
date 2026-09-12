"""Candidates HTTP router."""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.domains.candidates import presenter, service
from app.domains.candidates.exceptions import CandidateNotFound, JobNotFound
from app.domains.jobs.schemas import AssignCandidatesRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/candidates", tags=["candidates"])
assign_router = APIRouter(prefix="/api/jobs", tags=["job-candidates"])


def _require_candidate(
    db: Session,
    candidate_id: str,
    owner_sub: str,
):
    try:
        return service.require_candidate(db, candidate_id, owner_sub)
    except CandidateNotFound:
        raise HTTPException(status_code=404, detail="Candidato no encontrado.")


def _require_job(db: Session, job_id: str, owner_sub: str):
    try:
        return service.require_job(db, job_id, owner_sub)
    except JobNotFound:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")


def _get_job_candidate_evaluation(
    db: Session,
    job_id: str,
    candidate_id: str,
    owner_sub: str,
):
    try:
        return service.get_job_candidate_evaluation(
            db,
            job_id,
            candidate_id,
            owner_sub,
        )
    except JobNotFound:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")
    except CandidateNotFound:
        raise HTTPException(status_code=404, detail="Candidato no encontrado.")


# ============================================================
# JOB-CANDIDATE ASSIGNMENT (under /api/jobs/{job_id}/candidates)
# ============================================================


@assign_router.post("/{job_id}/candidates")
def assign_candidates_to_job(
    job_id: str,
    body: AssignCandidatesRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id, _user["sub"])
    if not body.candidate_ids:
        raise HTTPException(status_code=400, detail="candidate_ids requerido.")

    try:
        assigned, skipped = service.assign_candidates(
            db,
            job_id,
            body.candidate_ids,
            _user["sub"],
        )
    except JobNotFound:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")

    return {"assigned": assigned, "skipped": skipped}


@assign_router.get("/{job_id}/candidates")
def get_job_candidates(
    job_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    try:
        items, _total = service.list_job_candidates(
            db,
            job_id,
            _user["sub"],
            page=page,
            page_size=page_size,
        )
    except JobNotFound:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")

    return [presenter.candidate_to_dict(candidate) for candidate in items]


@assign_router.get("/{job_id}/candidates/{candidate_id}")
def get_job_candidate_detail(
    job_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    evaluation = _get_job_candidate_evaluation(
        db,
        job_id,
        candidate_id,
        _user["sub"],
    )

    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluacion no encontrada.")

    return presenter.evaluation_to_dict(evaluation)


@assign_router.get("/{job_id}/candidates/{candidate_id}/explanation")
def get_candidate_explanation(
    job_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    evaluation = _get_job_candidate_evaluation(
        db,
        job_id,
        candidate_id,
        _user["sub"],
    )
    return presenter.evaluation_explanation_to_dict(evaluation)


@assign_router.get("/{job_id}/candidates/{candidate_id}/requirements")
def get_candidate_requirements(
    job_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    evaluation = _get_job_candidate_evaluation(
        db,
        job_id,
        candidate_id,
        _user["sub"],
    )
    return presenter.evaluation_requirements_to_dict(evaluation)


@router.get("")
def list_candidates(
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    candidates = service.list_candidates(db, _user["sub"])
    return [presenter.candidate_to_dict(candidate) for candidate in candidates]


@router.get("/{candidate_id}")
def get_candidate(
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    candidate = _require_candidate(db, candidate_id, _user["sub"])
    return presenter.candidate_to_dict(candidate)


@router.post("/bulk")
async def upload_candidates_bulk(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    results = []
    errors = []

    for upload in files:
        try:
            file_content = await upload.read()
            if not file_content:
                errors.append(
                    {
                        "original_filename": upload.filename,
                        "error": "Empty file",
                    }
                )
                continue

            candidate, indexing = service.create_and_index_candidate(
                db,
                owner_sub=_user["sub"],
                original_filename=upload.filename,
                file_content=file_content,
            )

            results.append(
                {
                    "candidate_id": candidate.id,
                    "name": candidate.name,
                    "original_filename": upload.filename,
                    "ingestion_status": indexing.get("status", "UNKNOWN"),
                    "ingestion_job_id": indexing.get("ingestion_job_id"),
                    "error": indexing.get("error"),
                }
            )
        except Exception as exc:
            logger.error(
                "Error processing %s: %s",
                upload.filename,
                exc,
                exc_info=True,
            )
            errors.append(
                {
                    "original_filename": upload.filename,
                    "error": str(exc),
                }
            )

    return {
        "processed": len(files),
        "successful": len(results),
        "failed": len(errors),
        "candidates": results,
        "errors": errors,
    }


@router.delete("")
def delete_all_candidates(
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    try:
        deleted, failed = service.delete_all_candidates(db, _user["sub"])
        return {"deleted": deleted, "failed": failed}
    except Exception as exc:
        logger.error("Error deleting all candidates: %s", exc)
        raise HTTPException(status_code=500, detail="Error al eliminar candidatos.")


@router.delete("/{candidate_id}")
def delete_candidate(
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    try:
        service.delete_candidate(db, candidate_id, _user["sub"])
        return {"detail": "Candidato eliminado."}
    except CandidateNotFound:
        raise HTTPException(status_code=404, detail="Candidato no encontrado.")
    except Exception as exc:
        logger.error("Error deleting candidate %s: %s", candidate_id, exc)
        raise HTTPException(status_code=500, detail="Error al eliminar candidato.")


@router.get("/{candidate_id}/download")
def download_candidate_cv(
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_candidate(db, candidate_id, _user["sub"])
    return {"download_url": None, "detail": "CV storage not configured."}


@router.get("/{candidate_id}/evaluations")
def get_candidate_evaluations(
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    try:
        evaluations = service.get_candidate_evaluations(
            db,
            candidate_id,
            _user["sub"],
        )
    except CandidateNotFound:
        raise HTTPException(status_code=404, detail="Candidato no encontrado.")

    return {
        "evaluations": [
            presenter.evaluation_to_dict(evaluation)
            for evaluation in evaluations
        ]
    }
