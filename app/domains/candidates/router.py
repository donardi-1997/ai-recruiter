"""Candidates router."""

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app import crud
from app.domains.candidates.schemas import (
    CandidateResponse,
    BulkUploadResponse,
    CandidateEvaluationsResponse,
)
from app.domains.jobs.schemas import AssignCandidatesRequest
from app.infrastructure.storage.candidate_documents import index_candidate_document

router = APIRouter(prefix="/api/candidates", tags=["candidates"])


def _require_candidate(
    db: Session,
    candidate_id: str,
    owner_sub: str,
):
    candidate = crud.get_candidate(db, candidate_id, owner_sub=owner_sub)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidato no encontrado.")
    return candidate


def _require_job(db: Session, job_id: str, owner_sub: str):
    job = crud.get_job(db, job_id, owner_sub=owner_sub)
    if not job:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")
    return job


# ============================================================
# JOB-CANDIDATE ASSIGNMENT (under /api/jobs/{job_id}/candidates)
# ============================================================

assign_router = APIRouter(prefix="/api/jobs", tags=["job-candidates"])


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
    assigned, skipped = crud.assign_candidates_to_job(
        db,
        job_id,
        body.candidate_ids,
        owner_sub=_user["sub"],
    )
    return {"assigned": assigned, "skipped": skipped}


@assign_router.get("/{job_id}/candidates")
def get_job_candidates(
    job_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id, _user["sub"])
    items, total = crud.list_candidates_for_job(
        db,
        job_id,
        page=page,
        page_size=page_size,
        owner_sub=_user["sub"],
    )
    return [
        {
            "candidate_id": c.id,
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "metadata": c.metadata_,
            "filename": c.metadata_.get("filename") if c.metadata_ else None,
        }
        for c in items
    ]


@assign_router.get("/{job_id}/candidates/{candidate_id}")
def get_job_candidate_detail(
    job_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id, _user["sub"])
    _require_candidate(db, candidate_id, _user["sub"])

    evaluation = crud.get_evaluation_for_job_candidate(
        db,
        job_id,
        candidate_id,
    )

    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluacion no encontrada.")

    return {
        "evaluation_id": evaluation.id,
        "candidate_id": evaluation.candidate_id,
        "job_id": evaluation.job_id,
        "status": evaluation.status,
        "match_score": None if evaluation.status == "FAILED" else evaluation.match_score,
        "recommendation": "EVALUATION_FAILED" if evaluation.status == "FAILED" else evaluation.recommendation,
        "summary": "No fue posible completar la evaluación. Intenta nuevamente." if evaluation.status == "FAILED" else (evaluation.summary or ""),
        "strengths": [] if evaluation.status == "FAILED" else (evaluation.strengths or []),
        "gaps": [] if evaluation.status == "FAILED" else (evaluation.gaps or []),
        "requirements": [] if evaluation.status == "FAILED" else (evaluation.requirements or []),
        "error_message": "No fue posible completar la evaluación. Intenta nuevamente." if evaluation.status == "FAILED" else None,
    }


@assign_router.get("/{job_id}/candidates/{candidate_id}/explanation")
def get_candidate_explanation(
    job_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id, _user["sub"])
    _require_candidate(db, candidate_id, _user["sub"])

    evaluation = crud.get_evaluation_for_job_candidate(db, job_id, candidate_id)

    if not evaluation:
        return {
            "status": "PENDING",
            "explanation": "Sin evaluacion.",
            "summary": None,
            "analysis": None,
        }

    failed = evaluation.status == "FAILED"
    FAILED_EVALUATION_PUBLIC_MESSAGE = "No fue posible completar la evaluación. Intenta nuevamente."

    return {
        "status": evaluation.status,
        "explanation": FAILED_EVALUATION_PUBLIC_MESSAGE if failed else (evaluation.summary or ""),
        "summary": FAILED_EVALUATION_PUBLIC_MESSAGE if failed else (evaluation.summary or ""),
        "analysis": None,
    }


@assign_router.get("/{job_id}/candidates/{candidate_id}/requirements")
def get_candidate_requirements(
    job_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id, _user["sub"])
    _require_candidate(db, candidate_id, _user["sub"])

    evaluation = crud.get_evaluation_for_job_candidate(db, job_id, candidate_id)

    if not evaluation:
        return {"requirements": []}

    if evaluation.requirements:
        return {"requirements": evaluation.requirements}

    requirements = []
    for strength in evaluation.strengths or []:
        requirements.append({"requirement": strength, "status": "MATCH", "evidence": None})
    for gap in evaluation.gaps or []:
        requirements.append({"requirement": gap, "status": "MISSING", "evidence": None})

    return {"requirements": requirements}


@router.get("")
def list_candidates(
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    candidates = crud.list_candidates(db, owner_sub=_user["sub"])
    return [
        {
            "candidate_id": c.id,
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "metadata": c.metadata_,
            "filename": c.metadata_.get("filename") if c.metadata_ else None,
        }
        for c in candidates
    ]


@router.get("/{candidate_id}")
def get_candidate(
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    c = _require_candidate(db, candidate_id, _user["sub"])
    return {
        "candidate_id": c.id,
        "id": c.id,
        "name": c.name,
        "email": c.email,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "metadata": c.metadata_,
        "filename": c.metadata_.get("filename") if c.metadata_ else None,
    }


@router.post("/bulk")
async def upload_candidates_bulk(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    results = []
    errors = []
    for f in files:
        try:
            name = f.filename or "Unknown"
            import os
            name = os.path.splitext(name)[0]
            file_content = await f.read()
            if not file_content:
                errors.append({"original_filename": f.filename, "error": "Empty file"})
                continue

            candidate = crud.create_candidate(
                db,
                name=name,
                metadata={"filename": f.filename},
                owner_sub=_user["sub"],
            )

            indexing = index_candidate_document(candidate, file_content, f.filename)

            results.append({
                "candidate_id": candidate.id,
                "name": candidate.name,
                "original_filename": f.filename,
                "ingestion_status": indexing.get("status", "UNKNOWN"),
                "ingestion_job_id": indexing.get("ingestion_job_id"),
                "error": indexing.get("error"),
            })
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.error("Error processing %s: %s", f.filename, exc, exc_info=True)
            errors.append({"original_filename": f.filename, "error": str(exc)})

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
        deleted, failed = crud.delete_all_candidates(
            db,
            owner_sub=_user["sub"],
        )
        return {"deleted": deleted, "failed": failed}
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error("Error deleting all candidates: %s", exc)
        raise HTTPException(status_code=500, detail="Error al eliminar candidatos.")


@router.delete("/{candidate_id}")
def delete_candidate(
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_candidate(db, candidate_id, _user["sub"])
    try:
        crud.delete_candidate(db, candidate_id)
        return {"detail": "Candidato eliminado."}
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
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
    _require_candidate(db, candidate_id, _user["sub"])
    evaluations = crud.get_evaluations_for_candidate(db, candidate_id)
    return {
        "evaluations": [
            {
                "evaluation_id": e.id,
                "candidate_id": e.candidate_id,
                "job_id": e.job_id,
                "status": e.status,
                "match_score": None if e.status == "FAILED" else e.match_score,
                "recommendation": "EVALUATION_FAILED" if e.status == "FAILED" else e.recommendation,
                "summary": "No fue posible completar la evaluación. Intenta nuevamente." if e.status == "FAILED" else (e.summary or ""),
                "strengths": [] if e.status == "FAILED" else (e.strengths or []),
                "gaps": [] if e.status == "FAILED" else (e.gaps or []),
                "requirements": [] if e.status == "FAILED" else (e.requirements or []),
                "error_message": "No fue posible completar la evaluación. Intenta nuevamente." if e.status == "FAILED" else None,
            }
            for e in evaluations
        ]
    }