"""Authenticated Indeed integration routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.domains.indeed import service
from app.domains.indeed.exceptions import IndeedDisabled, IndeedLinkNotFound, IndeedNotConfigured, IndeedRemoteError, IndeedValidationError
from app.domains.jobs.exceptions import JobNotFound

router = APIRouter(tags=["indeed"])


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, JobNotFound):
        return HTTPException(status_code=404, detail="Vacante no encontrada.")
    if isinstance(exc, IndeedLinkNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, IndeedValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, (IndeedDisabled, IndeedNotConfigured)):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, IndeedRemoteError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail="Error interno del servidor.")


@router.get("/api/integrations/indeed/status")
def indeed_status(_user: dict = Depends(get_current_user)):
    return service.integration_status()


@router.post("/api/jobs/{job_id}/integrations/indeed/publish")
def publish(job_id: str, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    try:
        return service.publish_job(db, job_id=job_id, owner_sub=user["sub"])
    except Exception as exc:
        raise _translate(exc)


@router.get("/api/jobs/{job_id}/integrations/indeed/status")
def job_status(job_id: str, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    try:
        return service.get_job_status(db, job_id=job_id, owner_sub=user["sub"])
    except Exception as exc:
        raise _translate(exc)


@router.post("/api/jobs/{job_id}/integrations/indeed/expire")
def expire(job_id: str, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    try:
        return service.expire_job(db, job_id=job_id, owner_sub=user["sub"])
    except Exception as exc:
        raise _translate(exc)
