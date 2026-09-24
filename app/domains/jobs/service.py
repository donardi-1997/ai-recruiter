"""Application service for Jobs use cases."""

from sqlalchemy.orm import Session

from app.domains.jobs import repository
from app.domains.jobs.exceptions import JobNotFound
from app.domains.jobs.profile import (
    evaluation_signature,
    normalize_evaluation_profile,
)
from app.domains.jobs.reevaluation import schedule_reevaluation


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


def list_jobs_page(
    db: Session,
    *,
    owner_sub: str,
    page: int,
    page_size: int,
    sort: str,
    q: str = "",
):
    return repository.list_jobs_page(
        db,
        owner_sub=owner_sub,
        page=page,
        page_size=page_size,
        sort=sort,
        q=q,
    )


def create_job(
    db: Session,
    *,
    title: str,
    description: str | None,
    owner_sub: str,
    indeed_description: str | None = None,
    ai_description: str | None = None,
    active_description_source: str | None = None,
    evaluation_profile: dict | None = None,
    **publication_fields,
):
    kwargs = dict(
        title=title,
        description=description,
        owner_sub=owner_sub,
        **publication_fields,
    )

    source_fields_supplied = any(
        value is not None
        for value in (
            indeed_description,
            ai_description,
            active_description_source,
        )
    )
    if source_fields_supplied:
        source = active_description_source or "indeed"
        original = indeed_description if indeed_description is not None else description
        ai_value = ai_description
        effective = ai_value if source == "ai" else original
        if effective is None:
            effective = description
        kwargs.update(
            description=effective,
            indeed_description=original,
            ai_description=ai_value,
            active_description_source=source,
        )

    if evaluation_profile is not None:
        kwargs["evaluation_profile"] = normalize_evaluation_profile(evaluation_profile)
    return repository.create_job(db, **kwargs)


def update_job(
    db: Session,
    *,
    job_id: str,
    owner_sub: str,
    title: str | None = None,
    description: str | None = None,
    indeed_description: str | None = None,
    ai_description: str | None = None,
    active_description_source: str | None = None,
    evaluation_profile: dict | None = None,
    **publication_fields,
):
    job = require_job(db, job_id, owner_sub)

    # Backward-compatible path for lightweight domain fakes that predate job
    # intelligence. Real ORM Job objects always have these fields after 008.
    if not hasattr(job, "evaluation_version"):
        return repository.update_job(
            db,
            job,
            title=title,
            description=description,
            **publication_fields,
        )

    current_profile = normalize_evaluation_profile(
        getattr(job, "evaluation_profile", None)
    )
    next_title = job.title if title is None else title

    current_source = getattr(job, "active_description_source", None) or "indeed"
    current_indeed_description = getattr(job, "indeed_description", None)
    current_ai_description = getattr(job, "ai_description", None)
    if current_indeed_description is None and current_source == "indeed":
        current_indeed_description = job.description
    if current_ai_description is None and current_source == "ai":
        current_ai_description = job.description

    source_fields_supplied = any(
        value is not None
        for value in (
            indeed_description,
            ai_description,
            active_description_source,
        )
    )
    next_source = current_source if active_description_source is None else active_description_source
    next_indeed_description = (
        current_indeed_description
        if indeed_description is None
        else indeed_description
    )
    next_ai_description = (
        current_ai_description
        if ai_description is None
        else ai_description
    )

    # Compatibility for clients that still update only `description`: mutate
    # the currently active source instead of discarding the source model.
    if not source_fields_supplied and description is not None:
        if current_source == "ai":
            next_ai_description = description
        else:
            next_indeed_description = description

    next_description = (
        next_ai_description
        if next_source == "ai"
        else next_indeed_description
    )
    if next_description is None:
        next_description = job.description if description is None else description

    next_profile = (
        current_profile
        if evaluation_profile is None
        else normalize_evaluation_profile(evaluation_profile)
    )

    old_signature = evaluation_signature(
        job.title,
        job.description,
        current_profile,
    )
    new_signature = evaluation_signature(
        next_title,
        next_description,
        next_profile,
    )
    evaluation_changed = old_signature != new_signature
    next_version = int(getattr(job, "evaluation_version", 1) or 1)
    if evaluation_changed:
        next_version += 1

    try:
        updated = repository.update_job(
            db,
            job,
            title=title,
            description=next_description,
            indeed_description=next_indeed_description,
            ai_description=next_ai_description,
            active_description_source=next_source,
            evaluation_profile=(next_profile if evaluation_profile is not None else None),
            evaluation_version=next_version,
            commit=False,
            **publication_fields,
        )

        candidate_count = repository.count_candidates_for_job(
            db,
            updated.id,
            owner_sub=owner_sub,
        )
        reevaluation_scheduled = False
        if evaluation_changed and candidate_count > 0:
            schedule_reevaluation(
                db,
                job=updated,
                owner_sub=owner_sub,
            )
            reevaluation_scheduled = True

        # The job version and its durable reevaluation task are committed as one
        # transaction, preventing a successful edit from losing its work item.
        db.commit()
        db.refresh(updated)
    except Exception:
        db.rollback()
        raise

    # Transient response metadata; these values are not persisted on the Job.
    updated._evaluation_changed = evaluation_changed
    updated._reevaluation_scheduled = reevaluation_scheduled
    updated._reevaluation_candidate_count = candidate_count
    return updated


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
