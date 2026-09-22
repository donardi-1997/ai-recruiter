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


def _application_sort_key(task: IndeedEmailResumeTask, event: CandidateIngestionEvent) -> tuple[int, float, str]:
    metadata = dict(event.raw_metadata or {})
    try:
        internal_date_ms = int(metadata.get("internal_date_ms") or 0)
    except (TypeError, ValueError):
        internal_date_ms = 0
    created = getattr(event, "created_at", None) or getattr(task, "created_at", None)
    created_ts = created.timestamp() if created is not None else 0.0
    return (internal_date_ms, created_ts, str(task.id or ""))


def compact_duplicate_application_tasks(db, *, owner_sub: str) -> dict[str, int]:
    """Keep only the newest active Gmail task for one candidate + one vacancy.

    Historical completed tasks remain untouched. Different vacancies are separate
    groups, so one canonical candidate can still belong to multiple jobs.
    """
    rows = (
        db.query(IndeedEmailResumeTask, CandidateIngestionEvent)
        .join(
            CandidateIngestionEvent,
            CandidateIngestionEvent.id == IndeedEmailResumeTask.ingestion_event_id,
        )
        .filter(
            IndeedEmailResumeTask.owner_sub == owner_sub,
            IndeedEmailResumeTask.job_id.is_not(None),
            IndeedEmailResumeTask.status.in_(
                ("WAITING_DOWNLOAD", "RETRY", "NEEDS_HUMAN", "FAILED")
            ),
        )
        .all()
    )
    groups: dict[tuple[str, str], list[tuple[IndeedEmailResumeTask, CandidateIngestionEvent]]] = {}
    for task, event in rows:
        key = (str(task.job_id), _normalized_name(task.candidate_name))
        groups.setdefault(key, []).append((task, event))

    superseded = 0
    requeued_ambiguity = 0
    for group in groups.values():
        winner_task, _winner_event = max(
            group,
            key=lambda pair: _application_sort_key(pair[0], pair[1]),
        )
        for task, event in group:
            if task.id == winner_task.id:
                continue
            task.status = "IGNORED"
            task.available_at = None
            task.lease_token = None
            task.lease_expires_at = None
            task.claimed_at = None
            task.last_error_code = "SUPERSEDED_BY_NEWER_APPLICATION"
            task.last_error_message = "Existe una postulacion mas reciente para el mismo candidato y vacante."
            if str(event.status or "") not in {"COMPLETED"}:
                event.status = "IGNORED"
                event.last_error_code = "SUPERSEDED_BY_NEWER_APPLICATION"
                event.last_error_message = task.last_error_message
            superseded += 1

        if (
            winner_task.status == "NEEDS_HUMAN"
            and winner_task.last_error_code == "INDEED_CANDIDATE_AMBIGUOUS"
        ):
            winner_task.status = "WAITING_DOWNLOAD"
            winner_task.available_at = None
            winner_task.attempt_count = 0
            winner_task.last_error_code = None
            winner_task.last_error_message = None
            requeued_ambiguity += 1

    if superseded or requeued_ambiguity:
        db.commit()
    return {
        "superseded": superseded,
        "requeued_ambiguity": requeued_ambiguity,
    }


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
        .order_by(
            Job.title.asc(),
            Candidate.name.asc(),
            IndeedCandidateLink.staged_at.desc().nullslast(),
            IndeedCandidateLink.created_at.desc(),
            IndeedCandidateLink.id.desc(),
        )
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

    seen_candidate_jobs: set[tuple[str, str]] = set()
    for link, candidate, job, resume in rows:
        pair = (str(candidate.id), str(job.id))
        if pair in seen_candidate_jobs:
            continue
        seen_candidate_jobs.add(pair)
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
    compact = compact_duplicate_application_tasks(db, owner_sub=owner_sub)
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
        "superseded_duplicate_applications": compact["superseded"],
        "requeued_candidate_ambiguity": compact["requeued_ambiguity"],
    }
