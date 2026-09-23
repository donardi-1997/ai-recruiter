"""Idempotent Indeed Employers vacancy synchronization for the desktop agent."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.domains.candidate_ingestion import job_resolution
from app.domains.candidate_ingestion.models import (
    CandidateIngestionEvent,
    IndeedEmailResumeTask,
)
from app.domains.jobs import service as jobs_service
from app.models import IndeedJobLink, Job

DISCOVERY_PREFIX = "employer-ui:"
_JOB_NOT_SYNCED_CODE = "INDEED_JOB_NOT_SYNCED_YET"
_RESUME_PENDING_CODE = "RESUME_DOWNLOAD_PENDING"


def _clean(value) -> str:
    return " ".join(str(value or "").split()).strip()


def _canonical_title(value) -> str:
    text = unicodedata.normalize("NFKD", _clean(value).casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _discovery_key(value) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    return raw if raw.startswith(DISCOVERY_PREFIX) else f"{DISCOVERY_PREFIX}{raw}"


def _fingerprint(snapshot: dict) -> str:
    payload = {
        "title": _clean(snapshot.get("title")),
        "description": str(snapshot.get("description") or "").strip(),
        "status": _clean(snapshot.get("status")).upper(),
        "location": _clean(snapshot.get("location")),
        "posted_at": _clean(snapshot.get("posted_at")),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _external_status(snapshot: dict, fingerprint: str) -> dict:
    return {
        "origin": "EMPLOYER_UI",
        "status": _clean(snapshot.get("status")).upper() or None,
        "location": _clean(snapshot.get("location")) or None,
        "posted_at": _clean(snapshot.get("posted_at")) or None,
        "snapshot_fingerprint": fingerprint,
    }


def _find_link(db: Session, *, owner_sub: str, discovery_key: str) -> IndeedJobLink | None:
    return (
        db.query(IndeedJobLink)
        .filter(
            IndeedJobLink.owner_sub == owner_sub,
            IndeedJobLink.discovery_key == discovery_key,
        )
        .one_or_none()
    )


def _unlinked_title_matches(db: Session, *, owner_sub: str, title: str) -> list[Job]:
    target = _canonical_title(title)
    if not target:
        return []
    linked_job_ids = {
        job_id
        for (job_id,) in db.query(IndeedJobLink.job_id)
        .filter(IndeedJobLink.owner_sub == owner_sub)
        .all()
    }
    return [
        job
        for job in db.query(Job).filter(Job.owner_sub == owner_sub).all()
        if job.id not in linked_job_ids and _canonical_title(job.title) == target
    ]


def _update_existing_job(
    db: Session,
    *,
    job: Job,
    owner_sub: str,
    title: str,
    description: str,
) -> tuple[Job, bool]:
    had_description = bool(str(job.indeed_description or "").strip())
    updated = jobs_service.update_job(
        db,
        job_id=job.id,
        owner_sub=owner_sub,
        title=title if title != job.title else None,
        indeed_description=description,
    )
    return updated, (not had_description and bool(description))


def _existing_resume_task(
    db: Session,
    *,
    event_id: str,
) -> IndeedEmailResumeTask | None:
    return (
        db.query(IndeedEmailResumeTask)
        .filter(IndeedEmailResumeTask.ingestion_event_id == event_id)
        .one_or_none()
    )


def recover_waiting_applications(db: Session, *, owner_sub: str) -> int:
    """Wake applications whose canonical Indeed vacancy now exists.

    This repair belongs to the full/incremental application sync, not to the
    standalone vacancy refresh action. It also repairs historical unresolved
    tasks created before Gmail stopped creating vacancies.
    """
    events = (
        db.query(CandidateIngestionEvent)
        .outerjoin(
            IndeedEmailResumeTask,
            IndeedEmailResumeTask.ingestion_event_id == CandidateIngestionEvent.id,
        )
        .filter(
            CandidateIngestionEvent.owner_sub == owner_sub,
            CandidateIngestionEvent.source == "EMAIL",
            CandidateIngestionEvent.provider == "INDEED",
            or_(
                and_(
                    CandidateIngestionEvent.status == "NEEDS_REVIEW",
                    CandidateIngestionEvent.last_error_code == _JOB_NOT_SYNCED_CODE,
                ),
                and_(
                    IndeedEmailResumeTask.job_id.is_(None),
                    IndeedEmailResumeTask.status.in_(("WAITING_DOWNLOAD", "RETRY", "CLAIMED")),
                ),
            ),
        )
        .order_by(CandidateIngestionEvent.created_at.asc())
        .all()
    )
    recovered = 0
    for event in events:
        metadata = dict(event.raw_metadata or {})
        job = job_resolution.resolve_or_create_indeed_job(
            db,
            owner_sub=owner_sub,
            metadata=metadata,
        )
        if job is None:
            continue

        candidate_name = _clean(metadata.get("candidate_name"))
        job_title = _clean(metadata.get("job_title")) or _clean(job.title)
        if not candidate_name or not job_title:
            continue

        task = _existing_resume_task(db, event_id=event.id)
        if task is None:
            task = IndeedEmailResumeTask(
                owner_sub=owner_sub,
                ingestion_event_id=event.id,
                job_id=job.id,
                candidate_name=candidate_name,
                job_title=job_title,
                status="WAITING_DOWNLOAD",
            )
            db.add(task)
        else:
            task.job_id = job.id
            task.candidate_name = candidate_name
            task.job_title = job_title
            task.status = "WAITING_DOWNLOAD"
            task.attempt_count = 0
            task.available_at = None
            task.lease_token = None
            task.lease_expires_at = None
            task.claimed_at = None
            task.completed_at = None
            task.last_error_code = None
            task.last_error_message = None

        event.job_id = job.id
        event.status = "RECEIVED"
        event.last_error_code = _RESUME_PENDING_CODE
        event.last_error_message = "El CV de Indeed esta pendiente de descarga."
        recovered += 1

    if recovered:
        db.commit()
    return recovered


def sync_vacancy_snapshots(
    db: Session,
    *,
    owner_sub: str,
    snapshots: list[dict],
) -> dict[str, int]:
    """Reconcile normalized Indeed Employers vacancy snapshots for one owner.

    Provider identity wins. A title-only historical vacancy may be adopted only
    when exactly one unlinked owner-scoped match exists. Empty provider content
    never erases stored descriptions, and an active AI description remains the
    effective evaluation description while the original Indeed copy refreshes.
    This function deliberately does not read Gmail or mutate candidate tasks.
    """
    counts = {
        "discovered": len(snapshots or []),
        "created": 0,
        "updated": 0,
        "reconciled": 0,
        "unchanged": 0,
        "missing_identity": 0,
        "missing_description": 0,
        "ambiguous": 0,
        "descriptions_recovered": 0,
    }

    for raw in snapshots or []:
        snapshot = dict(raw or {})
        discovery_key = _discovery_key(snapshot.get("external_job_key"))
        title = _clean(snapshot.get("title"))
        description = str(snapshot.get("description") or "").strip()

        if not discovery_key or not title:
            counts["missing_identity"] += 1
            continue

        link = _find_link(db, owner_sub=owner_sub, discovery_key=discovery_key)
        fingerprint = _fingerprint(snapshot)

        if link is not None:
            job = (
                db.query(Job)
                .filter(Job.id == link.job_id, Job.owner_sub == owner_sub)
                .one_or_none()
            )
            if job is None:
                counts["missing_identity"] += 1
                continue
            if not description:
                counts["missing_description"] += 1
                continue

            previous = dict(link.external_status or {})
            if (
                previous.get("snapshot_fingerprint") == fingerprint
                and _clean(job.title) == title
                and str(job.indeed_description or "").strip() == description
            ):
                counts["unchanged"] += 1
                link.last_synced_at = datetime.now(timezone.utc)
                db.commit()
                continue

            _updated, recovered = _update_existing_job(
                db,
                job=job,
                owner_sub=owner_sub,
                title=title,
                description=description,
            )
            link.external_status = _external_status(snapshot, fingerprint)
            link.last_synced_at = datetime.now(timezone.utc)
            link.last_error = None
            db.commit()
            counts["updated"] += 1
            if recovered:
                counts["descriptions_recovered"] += 1
            continue

        if not description:
            counts["missing_description"] += 1
            continue

        matches = _unlinked_title_matches(
            db,
            owner_sub=owner_sub,
            title=title,
        )
        if len(matches) > 1:
            counts["ambiguous"] += 1
            continue

        if len(matches) == 1:
            job = matches[0]
            _updated, recovered = _update_existing_job(
                db,
                job=job,
                owner_sub=owner_sub,
                title=title,
                description=description,
            )
            db.add(
                IndeedJobLink(
                    job_id=job.id,
                    owner_sub=owner_sub,
                    discovery_key=discovery_key,
                    external_status=_external_status(snapshot, fingerprint),
                    last_synced_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
            counts["reconciled"] += 1
            if recovered:
                counts["descriptions_recovered"] += 1
            continue

        job = Job(
            title=title,
            description=description,
            indeed_description=description,
            ai_description=None,
            active_description_source="indeed",
            owner_sub=owner_sub,
            evaluation_version=1,
            evaluation_profile={},
        )
        db.add(job)
        db.flush()
        db.add(
            IndeedJobLink(
                job_id=job.id,
                owner_sub=owner_sub,
                discovery_key=discovery_key,
                external_status=_external_status(snapshot, fingerprint),
                last_synced_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
        counts["created"] += 1
        counts["descriptions_recovered"] += 1

    return counts