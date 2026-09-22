"""Owner-scoped full synchronization orchestration for ASIATI Resume Agent."""

from __future__ import annotations

from app.domains.candidate_ingestion import gmail_integration, repository
from app.domains.candidate_ingestion.models import (
    CandidateIngestionEvent,
    IndeedEmailResumeTask,
)
from app.domains.indeed.resume_models import IndeedResumeIngestion
from app.models import Candidate, IndeedCandidateLink, Job

BOOTSTRAP_CURSOR_PREFIX = "GMAIL_BOOTSTRAP_V1:"
LOOKUP_SOURCE = "AGENT"
LOOKUP_PROVIDER = "INDEED"
LOOKUP_ACCOUNT = "resume-agent"
LOOKUP_URL = "https://employers.indeed.com/candidates"
ACTIVE_RESUME_STATUSES = {
    "PENDING",
    "DOWNLOADING",
    "STORED",
    "INGESTING",
    "EVALUATING",
    "RANKING",
}


def _normalized_name(value: str | None) -> str:
    return " ".join(str(value or "").casefold().split())


def _lookup_event_external_id(candidate_link_id: str) -> str:
    return f"indeed-candidate-link:{candidate_link_id}"


def _has_existing_agent_task(
    db,
    *,
    owner_sub: str,
    job_id: str,
    candidate_name: str,
) -> bool:
    target = _normalized_name(candidate_name)
    tasks = (
        db.query(IndeedEmailResumeTask)
        .filter(
            IndeedEmailResumeTask.owner_sub == owner_sub,
            IndeedEmailResumeTask.job_id == job_id,
            IndeedEmailResumeTask.status != "IGNORED",
        )
        .all()
    )
    return any(_normalized_name(task.candidate_name) == target for task in tasks)


def reconcile_existing_indeed_candidates(db, *, owner_sub: str) -> dict[str, int]:
    """Queue browser fallbacks only when current Indeed resume retrieval is unavailable.

    Completed canonical resumes are left untouched. Provider resume ingestions that
    are still active are also left alone so the local agent never duplicates work.
    Failed/missing provider resume ingestions get one idempotent lookup-only task.
    """
    rows = (
        db.query(IndeedCandidateLink, Candidate, Job, IndeedResumeIngestion)
        .join(Candidate, Candidate.id == IndeedCandidateLink.candidate_id)
        .join(Job, Job.id == IndeedCandidateLink.job_id)
        .outerjoin(
            IndeedResumeIngestion,
            IndeedResumeIngestion.candidate_link_id == IndeedCandidateLink.id,
        )
        .filter(
            IndeedCandidateLink.owner_sub == owner_sub,
            Candidate.owner_sub == owner_sub,
            Job.owner_sub == owner_sub,
        )
        .order_by(Job.title.asc(), Candidate.name.asc(), IndeedCandidateLink.id.asc())
        .all()
    )

    counts = {
        "jobs_scanned": (
            db.query(Job)
            .filter(Job.owner_sub == owner_sub)
            .count()
        ),
        "scanned": 0,
        "ready": 0,
        "provider_pending": 0,
        "covered": 0,
        "queued": 0,
    }

    for link, candidate, job, resume in rows:
        counts["scanned"] += 1

        if (
            resume is not None
            and str(resume.status or "").upper() == "COMPLETED"
            and resume.canonical_s3_key
        ):
            counts["ready"] += 1
            continue

        if resume is not None and str(resume.status or "").upper() in ACTIVE_RESUME_STATUSES:
            counts["provider_pending"] += 1
            continue

        # A canonical document processed by any ingestion path leaves filename
        # metadata on the candidate. Do not redownload it just because a provider
        # resume task failed historically.
        metadata = dict(candidate.metadata_ or {})
        if str(metadata.get("filename") or "").strip():
            counts["ready"] += 1
            continue

        if _has_existing_agent_task(
            db,
            owner_sub=owner_sub,
            job_id=job.id,
            candidate_name=candidate.name,
        ):
            counts["covered"] += 1
            continue

        external_id = _lookup_event_external_id(link.id)
        event = repository.get_event_by_external_id(
            db,
            owner_sub=owner_sub,
            source=LOOKUP_SOURCE,
            provider=LOOKUP_PROVIDER,
            source_account=LOOKUP_ACCOUNT,
            external_id=external_id,
        )
        if event is None:
            event = repository.create_event(
                db,
                owner_sub=owner_sub,
                source=LOOKUP_SOURCE,
                provider=LOOKUP_PROVIDER,
                source_account=LOOKUP_ACCOUNT,
                external_id=external_id,
                status="RECEIVED",
                raw_metadata={
                    "resume_agent_lookup_only": True,
                    "candidate_name": candidate.name,
                    "job_title": job.title,
                    "indeed_candidate_link_id": link.id,
                },
            )
            event.job_id = job.id
            event.candidate_id = candidate.id
            event.last_error_code = "RESUME_DOWNLOAD_PENDING"
            event.last_error_message = "El CV de Indeed esta pendiente de descarga por el agente."

        task = (
            db.query(IndeedEmailResumeTask)
            .filter(IndeedEmailResumeTask.ingestion_event_id == event.id)
            .one_or_none()
        )
        if task is None:
            db.add(
                IndeedEmailResumeTask(
                    owner_sub=owner_sub,
                    ingestion_event_id=event.id,
                    job_id=job.id,
                    candidate_name=candidate.name,
                    job_title=job.title,
                    status="WAITING_DOWNLOAD",
                )
            )
            counts["queued"] += 1
        else:
            counts["covered"] += 1

    db.commit()
    return counts


def sync_one_page(
    db,
    *,
    owner_sub: str,
    mailbox_client=None,
    max_results: int = 20,
) -> dict:
    """Synchronize one bounded Gmail page and reconcile existing Indeed candidates.

    Keep each HTTP request comfortably below the desktop agent's 30-second timeout.
    The client exhausts the durable Gmail bootstrap cursor by calling this endpoint
    repeatedly, so smaller pages preserve correctness while avoiding long requests.
    """
    gmail = gmail_integration.sync_mailbox(
        db,
        owner_sub=owner_sub,
        mailbox_client=mailbox_client,
        max_results=max_results,
    )
    reconcile = reconcile_existing_indeed_candidates(db, owner_sub=owner_sub)
    cursor = str(gmail.get("cursor_value") or "")
    return {
        "mode": str(gmail.get("mode") or ""),
        "discovered": int(gmail.get("discovered") or 0),
        "created": int(gmail.get("created") or 0),
        "existing": int(gmail.get("existing") or 0),
        "needs_review": int(gmail.get("needs_review") or 0),
        "skipped": int(gmail.get("skipped") or 0),
        "has_more": cursor.startswith(BOOTSTRAP_CURSOR_PREFIX),
        "reconcile_jobs": reconcile["jobs_scanned"],
        "reconcile_scanned": reconcile["scanned"],
        "reconcile_ready": reconcile["ready"],
        "reconcile_provider_pending": reconcile["provider_pending"],
        "reconcile_covered": reconcile["covered"],
        "reconcile_queued": reconcile["queued"],
    }
