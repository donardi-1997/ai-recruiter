"""Indeed integration application service."""

from app.config import IndeedSettings, get_indeed_settings
from app.domains.candidates import repository as candidates_repository
from app.domains.candidates import service as candidates_service
from app.domains.indeed import candidates as candidate_sync
from app.domains.indeed import dispositions, mapper, repository, resume_repository
from app.domains.indeed.client import IndeedClient
from app.domains.indeed.exceptions import IndeedDisabled, IndeedLinkNotFound, IndeedNotConfigured, IndeedRemoteError
from app.domains.jobs.service import require_job
from app.infrastructure.imports import storage

CREATE_JOB = """mutation CreateSourcedJobPostings($input: CreateSourcedJobPostingsInput) { jobsIngest { createSourcedJobPostings(input: $input) { results { jobPosting { sourcedPostingId employerJobId } } } } }"""
EXPIRE_JOB = """mutation ExpireSourcedJobsBySourcedPostingId($input: ExpireSourcedJobsBySourcedPostingIdInput!) { jobsIngest { expireSourcedJobsBySourcedPostingId(input: $input) { results { trackingKey inputData { ... on ExpireSourcedJobBySourcedPostingIdInfo { sourcedPostingId } } } } } }"""
JOB_STATUS = """query GetIndeedJobStatus($id: ID!) { node(id: $id) { ... on EmployerJob { id seats { jobPost { id status { globalStatus { lifecycleStatus isIndeedApplyActive } surfaceStatuses { isRejected isSponsorshipRequired isMissingRequiredSponsorship } } } } } } }"""


def _settings(settings: IndeedSettings | None = None) -> IndeedSettings:
    value = settings or get_indeed_settings()
    if not value.enabled:
        raise IndeedDisabled("Indeed integration is disabled")
    if not value.configured:
        raise IndeedNotConfigured("Indeed integration is not configured")
    return value


def integration_status(settings: IndeedSettings | None = None) -> dict:
    value = settings or get_indeed_settings()
    return {
        "enabled": value.enabled,
        "configured": value.configured,
        "employer_id_configured": bool(value.employer_id),
        "candidate_sync_available": value.enabled and value.configured,
        "disposition_sync_available": value.enabled and value.configured,
    }


def publish_job(db, *, job_id: str, owner_sub: str, client: IndeedClient | None = None, settings: IndeedSettings | None = None) -> dict:
    cfg = _settings(settings)
    job = require_job(db, job_id, owner_sub)
    repository.get_or_create_connection(db, owner_sub, cfg.employer_id)
    event = repository.start_event(db, owner_sub=owner_sub, job_id=job_id, operation="PUBLISH")
    try:
        input_data = mapper.build_job_input(job, careers_base_url=cfg.careers_base_url, source_name=cfg.source_name, company_name=cfg.company_name)
        data = (client or IndeedClient(cfg)).execute(CREATE_JOB, {"input": input_data})
        results = data.get("jobsIngest", {}).get("createSourcedJobPostings", {}).get("results", [])
        posting = results[0].get("jobPosting") if results else None
        if not posting or not posting.get("sourcedPostingId") or not posting.get("employerJobId"):
            raise IndeedRemoteError("Indeed did not return a job posting identifier")
        link = repository.upsert_job_link(db, job_id=job_id, owner_sub=owner_sub, sourced_posting_id=posting["sourcedPostingId"], employer_job_id=posting["employerJobId"])
        repository.finish_event(db, event, external_id=link.sourced_posting_id)
        return {"job_id": job_id, "sourced_posting_id": link.sourced_posting_id, "employer_job_id": link.employer_job_id}
    except Exception as exc:
        repository.fail_event(db, event, exc)
        raise


def get_job_status(db, *, job_id: str, owner_sub: str, client: IndeedClient | None = None, settings: IndeedSettings | None = None) -> dict:
    cfg = _settings(settings)
    require_job(db, job_id, owner_sub)
    link = repository.get_job_link(db, job_id, owner_sub)
    if link is None or not link.employer_job_id:
        raise IndeedLinkNotFound("Job has not been published to Indeed")
    event = repository.start_event(db, owner_sub=owner_sub, job_id=job_id, operation="STATUS")
    try:
        data = (client or IndeedClient(cfg)).execute(JOB_STATUS, {"id": link.employer_job_id})
        node = data.get("node")
        if not node:
            raise IndeedRemoteError("Indeed job was not found")
        seats = node.get("seats") or []
        job_post = next((seat.get("jobPost") for seat in seats if seat.get("jobPost")), None)
        status = (job_post or {}).get("status") or {}
        repository.update_status(db, link, status)
        repository.finish_event(db, event, external_id=link.sourced_posting_id)
        return {"job_id": job_id, "sourced_posting_id": link.sourced_posting_id, "employer_job_id": link.employer_job_id, "status": status}
    except Exception as exc:
        repository.fail_event(db, event, exc)
        raise


def expire_job(db, *, job_id: str, owner_sub: str, client: IndeedClient | None = None, settings: IndeedSettings | None = None) -> dict:
    cfg = _settings(settings)
    require_job(db, job_id, owner_sub)
    link = repository.get_job_link(db, job_id, owner_sub)
    if link is None or not link.sourced_posting_id:
        raise IndeedLinkNotFound("Job has not been published to Indeed")
    event = repository.start_event(db, owner_sub=owner_sub, job_id=job_id, operation="EXPIRE")
    try:
        (client or IndeedClient(cfg)).execute(EXPIRE_JOB, {"input": {"jobs": [{"sourcedPostingId": link.sourced_posting_id}]}})
        repository.update_status(db, link, {"lifecycleStatus": "EXPIRE_REQUESTED"})
        repository.finish_event(db, event, external_id=link.sourced_posting_id)
        return {"job_id": job_id, "sourced_posting_id": link.sourced_posting_id, "status": "EXPIRE_REQUESTED"}
    except Exception as exc:
        repository.fail_event(db, event, exc)
        raise


def sync_candidates(
    db,
    *,
    owner_sub: str,
    limit: int = 25,
    client: IndeedClient | None = None,
    settings: IndeedSettings | None = None,
) -> dict:
    cfg = _settings(settings)
    return candidate_sync.fetch_candidate_assets(
        db,
        owner_sub=owner_sub,
        settings=cfg,
        client=client,
        limit=limit,
    )


def get_candidate_details(db, *, owner_sub: str, job_id: str, candidate_id: str) -> dict:
    require_job(db, job_id, owner_sub)
    link = repository.get_candidate_link(
        db,
        owner_sub=owner_sub,
        job_id=job_id,
        candidate_id=candidate_id,
    )
    if link is None:
        raise IndeedLinkNotFound("Candidate was not sourced from Indeed for this job")

    resume_task = resume_repository.get_resume_ingestion_for_candidate_link(
        db,
        owner_sub=owner_sub,
        candidate_link_id=link.id,
    )
    resume_status = resume_task.status if resume_task is not None else (
        "PENDING" if link.resume_name else "UNAVAILABLE"
    )
    resume_available = bool(
        resume_task is not None
        and resume_task.status == "COMPLETED"
        and resume_task.canonical_s3_key
    )

    return {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "source_name": link.source_name,
        "source_enum_key": link.source_enum_key,
        "resume_name": link.resume_name,
        # Internal compatibility only. The HTTP router removes this provider URL
        # before any response is returned to a browser.
        "resume_url": link.resume_url,
        "resume": {
            "name": link.resume_name,
            "status": resume_status,
            "available": resume_available,
            "sha256": resume_task.resume_sha256 if resume_task else None,
            "last_error_code": resume_task.last_error_code if resume_task else None,
        },
        "staged_test": bool(link.staged_test),
        "acknowledged_at": link.acknowledged_at.isoformat() if link.acknowledged_at else None,
    }


def get_canonical_resume_download(
    db,
    *,
    owner_sub: str,
    job_id: str,
    candidate_id: str,
) -> dict:
    require_job(db, job_id, owner_sub)
    candidates_service.require_candidate(db, candidate_id, owner_sub)
    assignment = candidates_repository.get_job_candidate(
        db,
        job_id=job_id,
        candidate_id=candidate_id,
        owner_sub=owner_sub,
    )
    if assignment is None:
        raise IndeedLinkNotFound("Candidate is not assigned to this job")

    download = storage.create_canonical_candidate_download(
        candidate_id,
        expires_in=300,
    )
    if download is None:
        raise IndeedLinkNotFound("Candidate resume is not available")
    return {
        "url": download["url"],
        "expires_in": download["expires_in"],
    }


def queue_candidate_status(
    db,
    *,
    owner_sub: str,
    job_id: str,
    candidate_id: str,
    local_status: str,
    status_changed_at,
):
    link = repository.get_candidate_link(
        db,
        owner_sub=owner_sub,
        job_id=job_id,
        candidate_id=candidate_id,
    )
    if link is None:
        return None
    return dispositions.queue_disposition_for_application(
        db,
        owner_sub=owner_sub,
        candidate_link=link,
        local_status=local_status,
        status_changed_at=status_changed_at,
    )


def sync_dispositions(
    db,
    *,
    owner_sub: str,
    limit: int = 25,
    client: IndeedClient | None = None,
    settings: IndeedSettings | None = None,
) -> dict:
    cfg = _settings(settings)
    return dispositions.sync_dispositions(
        db,
        owner_sub=owner_sub,
        settings=cfg,
        client=client,
        limit=limit,
    )
