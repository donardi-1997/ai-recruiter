"""Jobs router."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.domains.jobs import presenter, service
from app.domains.jobs.exceptions import JobNotFound
from app.domains.jobs.schemas import CreateJobRequest, UpdateJobRequest

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    return [
        presenter.job_payload(job, candidate_count=candidate_count)
        for job, candidate_count in service.list_jobs(db, _user["sub"])
    ]


@router.post("", status_code=201)
def create_job(
    body: CreateJobRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    job = service.create_job(
        db,
        title=body.title,
        description=body.description,
        owner_sub=_user["sub"],
    )
    return presenter.job_payload(job)


@router.put("/{job_id}")
def update_job(
    job_id: str,
    body: UpdateJobRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    try:
        job = service.update_job(
            db,
            job_id=job_id,
            title=body.title,
            description=body.description,
            owner_sub=_user["sub"],
        )
    except JobNotFound:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")

    return presenter.job_payload(job)


@router.delete("/{job_id}")
def delete_job(
    job_id: str,
    delete_candidates: bool = Query(False),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    try:
        deleted_count = service.delete_job(
            db,
            job_id=job_id,
            owner_sub=_user["sub"],
            delete_candidates=delete_candidates,
        )
    except JobNotFound:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")

    return presenter.delete_job_payload(
        job_id,
        delete_candidates,
        deleted_count,
    )
