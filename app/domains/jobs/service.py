"""Application service for Jobs use cases."""

from sqlalchemy.orm import Session

from app.domains.jobs import repository
from app.domains.jobs.exceptions import JobNotFound


def require_job(db: Session, job_id: str, owner_sub: str):
    job = repository.get_job(db, job_id, owner_sub=owner_sub)
    if job is None:
        raise JobNotFound(job_id)
    return job


def list_jobs(db: Session, owner_sub: str):
    jobs = repository.list_jobs(db, owner_sub=owner_sub)
    return [
        (
            job,
            repository.count_candidates_for_job(
                db,
                job.id,
                owner_sub=owner_sub,
            ),
        )
        for job in jobs
    ]


def create_job(
    db: Session,
    *,
    title: str,
    description: str | None,
    owner_sub: str,
):
    return repository.create_job(
        db,
        title=title,
        description=description,
        owner_sub=owner_sub,
    )


def update_job(
    db: Session,
    *,
    job_id: str,
    title: str | None,
    description: str | None,
    owner_sub: str,
):
    job = require_job(db, job_id, owner_sub)
    return repository.update_job(
        db,
        job,
        title=title,
        description=description,
    )


def delete_job(
    db: Session,
    *,
    job_id: str,
    owner_sub: str,
    delete_candidates: bool,
) -> int:
    require_job(db, job_id, owner_sub)
    success, deleted_count = repository.delete_job(
        db,
        job_id,
        owner_sub=owner_sub,
        delete_candidates=delete_candidates,
    )
    if not success:
        raise JobNotFound(job_id)
    return deleted_count
