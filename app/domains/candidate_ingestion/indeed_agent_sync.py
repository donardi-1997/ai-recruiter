"""Owner-scoped incremental synchronization orchestration for ASIATI Resume Agent."""

from __future__ import annotations

import re

from app.domains.candidate_ingestion import gmail_integration, indeed_job_sync, repository
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
_SAFE_STAGE_CODE = re.compile(r"\b((?:GMAIL|RESUME)_[A-Z0-9_]{2,100})\b")


class ResumeSyncStageError(RuntimeError):
    """Public-safe synchronization failure with a machine-readable stage code."""

    def __init__(self, code: str):
        self.code = str(code or "RESUME_SYNC_FAILED")
        super().__init__(self.code)


def _safe_exception_code(exc: Exception, fallback: str) -> str:
    match = _SAFE_STAGE_CODE.search(str(exc or ""))
    if match:
        return match.group(1)
    return fallback


def _run_stage(db, code: str, operation):
    try:
        return operation()
    except ResumeSyncStageError:
        raise
    except Exception as exc:
        db.rollback()
        raise ResumeSyncStageError(_safe_exception_code(exc, code)) from exc


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
    """Keep the newest active application only when canonical identity is known.

    Historical candidate-level attention is deliberately left untouched. A normal
    incremental sync must never turn an old review case back into browser work;
    only the explicit Retry attention action is allowed to do that.

    Names are deliberately not used as identity: two people can share the same
    name. Different vacancies remain independent associations for the same
    candidate.
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
            CandidateIngestionEvent.candidate_id.is_not(None),
            IndeedEmailResumeTask.status.in_(
                ("WAITING_DOWNLOAD", "RETRY", "NEEDS_HUMAN", "FAILED")
            ),
        )
        .all()
    )
    groups: dict[tuple[str, str], list[tuple[IndeedEmailResumeTask, CandidateIngestionEvent]]] = {}
    for task, event in rows:
        key = (str(task.job_id), str(event.candidate_id))
        groups.setdefault(key, []).append((task, event))

    superseded = 0
    for group in groups.values():
        if len(group) < 2:
            continue
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

    if superseded:
        db.commit()
    return {
        "superseded": superseded,
        "requeued_ambiguity": 0,
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

    This owner-wide reconciliation is reserved for first bootstrap/backlog repair.
    Normal incremental syncs do not call it.
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


def _empty_reconciliation() -> dict[str, int]:
    return {
        "jobs_scanned": 0,
        "scanned": 0,
        "ready": 0,
        "provider_pending": 0,
        "covered": 0,
        "queued": 0,
    }


def sync_one_page(
    db,
    *,
    owner_sub: str,
    mailbox_client=None,
    max_results: int = 20,
) -> dict:
    """Synchronize one bounded Gmail page without re-traversing completed people.

    Gmail's durable cursor is the source of incremental truth. Applications that
    were previously parked until their vacancy existed are repaired first. The
    expensive owner-wide provider reconciliation runs once on the initial FULL
    bootstrap; subsequent FULL_CONTINUE and INCREMENTAL pages operate only on
    newly created or explicitly recovered durable queue work.
    """
    applications_recovered = _run_stage(
        db,
        "RESUME_SYNC_RECOVERY_FAILED",
        lambda: indeed_job_sync.recover_waiting_applications(
            db,
            owner_sub=owner_sub,
        ),
    )
    gmail = _run_stage(
        db,
        "GMAIL_SYNC_FAILED",
        lambda: gmail_integration.sync_mailbox(
            db,
            owner_sub=owner_sub,
            mailbox_client=mailbox_client,
            max_results=max_results,
        ),
    )
    mode = str(gmail.get("mode") or "")
    created = int(gmail.get("created") or 0)

    compact = (
        _run_stage(
            db,
            "RESUME_SYNC_COMPACTION_FAILED",
            lambda: compact_duplicate_application_tasks(db, owner_sub=owner_sub),
        )
        if created > 0 or applications_recovered > 0
        else {"superseded": 0, "requeued_ambiguity": 0}
    )
    reconcile = (
        _run_stage(
            db,
            "RESUME_SYNC_RECONCILE_FAILED",
            lambda: reconcile_existing_indeed_candidates(db, owner_sub=owner_sub),
        )
        if mode == "FULL"
        else _empty_reconciliation()
    )
    cursor = str(gmail.get("cursor_value") or "")
    return {
        "mode": mode,
        "discovered": int(gmail.get("discovered") or 0),
        "created": created,
        "existing": int(gmail.get("existing") or 0),
        "needs_review": int(gmail.get("needs_review") or 0),
        "skipped": int(gmail.get("skipped") or 0),
        "has_more": cursor.startswith(BOOTSTRAP_CURSOR_PREFIX),
        "applications_recovered": applications_recovered,
        "reconcile_jobs": reconcile["jobs_scanned"],
        "reconcile_scanned": reconcile["scanned"],
        "reconcile_ready": reconcile["ready"],
        "reconcile_provider_pending": reconcile["provider_pending"],
        "reconcile_covered": reconcile["covered"],
        "reconcile_queued": reconcile["queued"],
        "superseded_duplicate_applications": compact["superseded"],
        "requeued_candidate_ambiguity": compact["requeued_ambiguity"],
    }