"""Jobs router."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.deps import get_db, require_permission
from app.domains.jobs import presenter, service
from app.domains.jobs.enrichment import JobEnrichmentError, enrich_job_draft
from app.domains.jobs.exceptions import JobNotFound
from app.domains.jobs.schemas import CreateJobRequest, JobEnrichmentRequest, UpdateJobRequest

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _publication_fields(body) -> dict:
    return {
        "country_code": body.country_code,
        "city": body.city,
        "employment_type": body.employment_type,
        "public_slug": body.public_slug,
        "published_at": body.published_at,
    }


def _evaluation_profile(body) -> dict | None:
    profile = body.evaluation_profile
    return profile.model_dump() if profile is not None else None


@router.get("")
def list_jobs(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("jobs.read")),
):
    return [
        presenter.job_payload(job, candidate_count=candidate_count)
        for job, candidate_count in service.list_jobs(db, _user["sub"])
    ]


@router.get("/page")
def list_jobs_page(
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("jobs.read")),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
    sort: Literal[
        "created_desc",
        "created_asc",
        "candidates_desc",
        "candidates_asc",
    ] = Query("created_desc"),
    q: str = Query("", max_length=120),
):
    rows, total = service.list_jobs_page(
        db,
        owner_sub=_user["sub"],
        page=page,
        page_size=page_size,
        sort=sort,
        q=q,
    )
    return {
        "items": [
            presenter.job_payload(job, candidate_count=int(candidate_count or 0))
            for job, candidate_count in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
    }


@router.post("/enrich")
def enrich_job(
    body: JobEnrichmentRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("jobs.read")),
):
    try:
        proposal, context_version = enrich_job_draft(
            db,
            owner_sub=_user["sub"],
            request=body,
        )
    except JobEnrichmentError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return {
        "company_context_version": context_version,
        "proposal": proposal.model_dump(),
    }


@router.post("", status_code=201)
def create_job(
    body: CreateJobRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("jobs.read")),
):
    job = service.create_job(
        db,
        title=body.title,
        description=body.description,
        indeed_description=body.indeed_description,
        ai_description=body.ai_description,
        active_description_source=body.active_description_source,
        evaluation_profile=_evaluation_profile(body),
        owner_sub=_user["sub"],
        **_publication_fields(body),
    )
    return presenter.job_payload(job)


@router.put("/{job_id}")
def update_job(
    job_id: str,
    body: UpdateJobRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("jobs.read")),
):
    try:
        job = service.update_job(
            db,
            job_id=job_id,
            title=body.title,
            description=body.description,
            indeed_description=body.indeed_description,
            ai_description=body.ai_description,
            active_description_source=body.active_description_source,
            evaluation_profile=_evaluation_profile(body),
            owner_sub=_user["sub"],
            **_publication_fields(body),
        )
    except JobNotFound:
        raise HTTPException(status_code=404, detail="Vacante no encontrada.")

    return presenter.job_payload(job)


@router.delete("/{job_id}")
def delete_job(
    job_id: str,
    delete_candidates: bool = Query(False),
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("jobs.read")),
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
