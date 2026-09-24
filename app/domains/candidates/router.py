"""Candidates HTTP router."""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.deps import get_db, require_permission
from app.domains.candidates import presenter, service
from app.domains.candidates.exceptions import (
    CandidateNotFound,
    InvalidApplicationStatus,
    JobCandidateNotFound,
    JobNotFound,
)
from app.domains.candidates.schemas import (
    ApplicationStatusRequest,
    CandidateRestrictionRequest,
)
from app.domains.jobs.schemas import AssignCandidatesRequest
from app.infrastructure.imports.documents import MAX_DOCUMENT_BYTES

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
    _user: dict = Depends(require_permission("candidates.read")),
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
    _user: dict = Depends(require_permission("candidates.read")),
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


@assign_router.put("/{job_id}/candidates/{candidate_id}/status")
def update_application_status(
    job_id: str,
    candidate_id: str,
    body: ApplicationStatusRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("candidates.read")),
):
    try:
        link, changed = service.set_application_status(
            db,
            job_id=job_id,
            candidate_id=candidate_id,
            status=body.status,
            owner_sub=_user["sub"],
        )
    except JobNotFound:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")
    except (CandidateNotFound, JobCandidateNotFound):
        raise HTTPException(status_code=404, detail="Candidato no encontrado en esta vacante.")
    except InvalidApplicationStatus:
        raise HTTPException(status_code=422, detail="Estado de aplicacion no valido.")

    return {
        "job_id": job_id,
        "candidate_id": candidate_id,
        "status": link.application_status,
        "status_changed_at": link.status_changed_at.isoformat() if link.status_changed_at else None,
        "changed": changed,
    }


@assign_router.get("/{job_id}/candidates/{candidate_id}")
def get_job_candidate_detail(
    job_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("candidates.read")),
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
    _user: dict = Depends(require_permission("candidates.read")),
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
    _user: dict = Depends(require_permission("candidates.read")),
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
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=20, le=20),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("candidates.read")),
):
    candidates, total = service.list_candidates_page(
        db,
        _user["sub"],
        page=page,
        page_size=page_size,
    )
    pages = (total + page_size - 1) // page_size if total else 0
    return {
        "items": [presenter.candidate_to_dict(candidate) for candidate in candidates],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


@router.get("/{candidate_id}")
def get_candidate(
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("candidates.read")),
):
    candidate = _require_candidate(db, candidate_id, _user["sub"])
    return presenter.candidate_to_dict(candidate)


@router.post("/bulk")
async def upload_candidates_bulk(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("candidates.read")),
):
    results = []
    errors = []

    for upload in files:
        public_filename = str(upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        try:
            file_content = await upload.read(MAX_DOCUMENT_BYTES + 1)
            if len(file_content) > MAX_DOCUMENT_BYTES:
                errors.append(
                    {
                        "original_filename": public_filename,
                        "error": "El archivo supera el limite de 15 MB.",
                    }
                )
                continue

            safe_filename = service.validate_legacy_candidate_pdf(
                original_filename=public_filename,
                file_content=file_content,
            )
            candidate, indexing = service.create_and_index_candidate(
                db,
                owner_sub=_user["sub"],
                original_filename=safe_filename,
                file_content=file_content,
            )

            results.append(
                {
                    "candidate_id": candidate.id,
                    "name": candidate.name,
                    "original_filename": public_filename,
                    "ingestion_status": indexing.get("status", "UNKNOWN"),
                    "ingestion_job_id": indexing.get("ingestion_job_id"),
                    "error": (
                        "No fue posible indexar el CV."
                        if indexing.get("error")
                        else None
                    ),
                }
            )
        except service.LegacyCandidateUploadError as exc:
            logger.info(
                "Legacy candidate upload rejected for %s: %s",
                public_filename,
                exc,
            )
            code = str(exc)
            public_error = {
                "LEGACY_UPLOAD_EMPTY": "El archivo esta vacio.",
                "LEGACY_UPLOAD_TOO_LARGE": "El archivo supera el limite de 15 MB.",
                "LEGACY_UPLOAD_PDF_ONLY": "Esta ruta solo admite archivos PDF.",
                "LEGACY_UPLOAD_INVALID_PDF": "El archivo PDF no es valido.",
            }.get(code, "El archivo no es valido.")
            errors.append(
                {
                    "original_filename": public_filename,
                    "error": public_error,
                }
            )
        except Exception as exc:
            logger.error(
                "Error processing legacy candidate upload %s: %s",
                public_filename,
                exc,
                exc_info=True,
            )
            errors.append(
                {
                    "original_filename": public_filename,
                    "error": "No fue posible procesar el CV.",
                }
            )

    return {
        "processed": len(files),
        "successful": len(results),
        "failed": len(errors),
        "candidates": results,
        "errors": errors,
    }


@router.post("/{candidate_id}/ban")
def ban_candidate(
    candidate_id: str,
    body: CandidateRestrictionRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("candidates.restrict")),
):
    try:
        candidate, event, changed = service.set_candidate_ban(
            db,
            candidate_id=candidate_id,
            owner_sub=_user["sub"],
            reason=body.reason,
            created_by_sub=_user["sub"],
            banned=True,
        )
    except CandidateNotFound:
        raise HTTPException(status_code=404, detail="Candidato no encontrado.")

    return {
        "candidate": presenter.candidate_to_dict(candidate),
        "event": presenter.restriction_event_to_dict(event) if event else None,
        "changed": changed,
    }


@router.post("/{candidate_id}/unban")
def unban_candidate(
    candidate_id: str,
    body: CandidateRestrictionRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("candidates.restrict")),
):
    try:
        candidate, event, changed = service.set_candidate_ban(
            db,
            candidate_id=candidate_id,
            owner_sub=_user["sub"],
            reason=body.reason,
            created_by_sub=_user["sub"],
            banned=False,
        )
    except CandidateNotFound:
        raise HTTPException(status_code=404, detail="Candidato no encontrado.")

    return {
        "candidate": presenter.candidate_to_dict(candidate),
        "event": presenter.restriction_event_to_dict(event) if event else None,
        "changed": changed,
    }


@router.get("/{candidate_id}/restrictions")
def get_candidate_restrictions(
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("candidates.restrict")),
):
    try:
        candidate, events = service.get_candidate_restriction_history(
            db,
            candidate_id=candidate_id,
            owner_sub=_user["sub"],
        )
    except CandidateNotFound:
        raise HTTPException(status_code=404, detail="Candidato no encontrado.")

    return {
        "candidate": presenter.candidate_to_dict(candidate),
        "events": [
            presenter.restriction_event_to_dict(event)
            for event in events
        ],
    }


@router.get("/{candidate_id}/download")
def download_candidate_cv(
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("candidates.read")),
):
    try:
        download = service.get_candidate_download(
            db,
            candidate_id,
            _user["sub"],
        )
    except CandidateNotFound:
        raise HTTPException(status_code=404, detail="Candidato no encontrado.")
    except Exception as exc:
        logger.error(
            "Candidate CV download failed candidate=%s error=%s",
            candidate_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="No fue posible preparar la descarga del CV.",
        ) from exc

    if download is None:
        raise HTTPException(status_code=404, detail="CV no disponible.")

    return {
        "download_url": download["url"],
        "expires_in": download["expires_in"],
    }


@router.get("/{candidate_id}/evaluations")
def get_candidate_evaluations(
    candidate_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("candidates.read")),
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
