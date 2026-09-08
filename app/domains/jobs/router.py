"""Jobs router."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app import crud
from app.domains.jobs.schemas import (
    CreateJobRequest,
    UpdateJobRequest,
    DeleteJobResponse,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _require_job(
    db: Session,
    job_id: str,
    owner_sub: str,
):
    job = crud.get_job(db, job_id, owner_sub=owner_sub)
    if not job:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")
    return job


@router.get("")
def list_jobs(
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    jobs = crud.list_jobs(db, owner_sub=_user["sub"])
    return [
        {
            "job_id": j.id,
            "id": j.id,
            "title": j.title,
            "description": j.description,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "candidate_count": crud.count_candidates_for_job(db, j.id, owner_sub=_user["sub"]),
        }
        for j in jobs
    ]


@router.post("", status_code=201)
def create_job(
    body: CreateJobRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    job = crud.create_job(
        db,
        title=body.title,
        description=body.description,
        owner_sub=_user["sub"],
    )
    return {
        "job_id": job.id,
        "id": job.id,
        "title": job.title,
        "description": job.description,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


@router.put("/{job_id}")
def update_job(
    job_id: str,
    body: UpdateJobRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    job = _require_job(db, job_id, _user["sub"])
    updated = crud.update_job(db, job, title=body.title, description=body.description)
    return {
        "job_id": updated.id,
        "id": updated.id,
        "title": updated.title,
        "description": updated.description,
        "created_at": updated.created_at.isoformat() if updated.created_at else None,
    }


@router.delete("/{job_id}")
def delete_job(
    job_id: str,
    delete_candidates: bool = Query(False),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _require_job(db, job_id, _user["sub"])
    success, deleted_count = crud.delete_job(
        db,
        job_id,
        owner_sub=_user["sub"],
        delete_candidates=delete_candidates,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")
    if delete_candidates:
        return {
            "detail": "Vacante y candidatos eliminados.",
            "job_id": job_id,
            "delete_candidates": True,
            "deleted_candidates": deleted_count,
        }
    return {
        "detail": "Vacante eliminada.",
        "job_id": job_id,
        "delete_candidates": False,
        "deleted_candidates": 0,
    }