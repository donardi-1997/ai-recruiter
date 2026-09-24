"""Authenticated Indeed integration routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.deps import get_db, require_permission
from app.domains.candidate_imports.exceptions import IdentityConflict
from app.domains.indeed import service
from app.domains.indeed.exceptions import (
    IndeedDisabled,
    IndeedLinkNotFound,
    IndeedNotConfigured,
    IndeedRemoteError,
    IndeedValidationError,
)
from app.domains.jobs.exceptions import JobNotFound

logger = logging.getLogger(__name__)

router = APIRouter(tags=["indeed"])


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, JobNotFound):
        return HTTPException(status_code=404, detail="Vacante no encontrada.")
    if isinstance(exc, IndeedLinkNotFound):
        return HTTPException(status_code=404, detail="Integracion de Indeed no encontrada.")
    if isinstance(exc, IdentityConflict):
        return HTTPException(status_code=409, detail="Conflicto de identidad de candidato.")
    if isinstance(exc, IndeedValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, IndeedDisabled):
        return HTTPException(status_code=503, detail="La integracion de Indeed esta deshabilitada.")
    if isinstance(exc, IndeedNotConfigured):
        return HTTPException(status_code=503, detail="La integracion de Indeed no esta configurada.")
    if isinstance(exc, IndeedRemoteError):
        logger.warning("Indeed remote operation failed: %s", exc)
        return HTTPException(
            status_code=502,
            detail="Indeed no pudo completar la operacion. Intenta nuevamente.",
        )
    logger.exception("Unexpected Indeed integration error", exc_info=exc)
    return HTTPException(status_code=500, detail="Error interno del servidor.")


@router.get("/api/integrations/indeed/status")
def indeed_status(_user: dict = Depends(require_permission("integrations.manage"))):
    return service.integration_status()


@router.post("/api/integrations/indeed/candidates/sync")
def sync_candidates(
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("integrations.manage")),
):
    try:
        return service.sync_candidates(
            db,
            owner_sub=user["sub"],
            limit=limit,
        )
    except Exception as exc:
        raise _translate(exc)


@router.post("/api/integrations/indeed/dispositions/sync")
def sync_dispositions(
    limit: int = Query(25, ge=1, le=25),
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("integrations.manage")),
):
    try:
        return service.sync_dispositions(
            db,
            owner_sub=user["sub"],
            limit=limit,
        )
    except Exception as exc:
        raise _translate(exc)


@router.post("/api/jobs/{job_id}/integrations/indeed/publish")
def publish(job_id: str, db: Session = Depends(get_db), user: dict = Depends(require_permission("integrations.manage"))):
    try:
        return service.publish_job(db, job_id=job_id, owner_sub=user["sub"])
    except Exception as exc:
        raise _translate(exc)


@router.get("/api/jobs/{job_id}/integrations/indeed/status")
def job_status(job_id: str, db: Session = Depends(get_db), user: dict = Depends(require_permission("integrations.manage"))):
    try:
        return service.get_job_status(db, job_id=job_id, owner_sub=user["sub"])
    except Exception as exc:
        raise _translate(exc)


@router.post("/api/jobs/{job_id}/integrations/indeed/expire")
def expire(job_id: str, db: Session = Depends(get_db), user: dict = Depends(require_permission("integrations.manage"))):
    try:
        return service.expire_job(db, job_id=job_id, owner_sub=user["sub"])
    except Exception as exc:
        raise _translate(exc)


@router.get("/api/jobs/{job_id}/candidates/{candidate_id}/integrations/indeed")
def candidate_details(
    job_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("integrations.manage")),
):
    try:
        payload = service.get_candidate_details(
            db,
            owner_sub=user["sub"],
            job_id=job_id,
            candidate_id=candidate_id,
        )
        # Provider pre-signed URLs are internal inputs. Recruiters only receive
        # canonical short-lived S3 URLs from the dedicated resume endpoint.
        payload.pop("resume_url", None)
        return payload
    except Exception as exc:
        raise _translate(exc)


@router.get("/api/jobs/{job_id}/candidates/{candidate_id}/resume")
def candidate_resume(
    job_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("integrations.manage")),
):
    """Return a short-lived canonical CV URL, never the Indeed provider URL."""
    try:
        return service.get_canonical_resume_download(
            db,
            owner_sub=user["sub"],
            job_id=job_id,
            candidate_id=candidate_id,
        )
    except Exception as exc:
        raise _translate(exc)
