"""Deterministic tenant-scoped job resolution for candidate ingestion."""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy.orm import Session

from app.domains.jobs import repository as jobs_repository
from app.models import IndeedJobLink, Job


def _normalize(value: str | None) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _canonical_title_key(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split()).strip(" .,-:;")


def indeed_discovery_key(metadata: dict | None) -> str | None:
    metadata = metadata or {}
    external_job_id = str(metadata.get("external_job_id") or "").strip()
    if external_job_id:
        return f"posting:{external_job_id.casefold()}"
    title_key = _canonical_title_key(metadata.get("job_title"))
    if title_key:
        return f"title:{title_key}"
    return None


def _job_by_discovery_key(
    db: Session,
    *,
    owner_sub: str,
    discovery_key: str,
) -> Job | None:
    return (
        db.query(Job)
        .join(IndeedJobLink, IndeedJobLink.job_id == Job.id)
        .filter(
            IndeedJobLink.owner_sub == owner_sub,
            IndeedJobLink.discovery_key == discovery_key,
            Job.owner_sub == owner_sub,
        )
        .one_or_none()
    )


def _job_by_sourced_posting_id(
    db: Session,
    *,
    owner_sub: str,
    sourced_posting_id: str,
) -> Job | None:
    return (
        db.query(Job)
        .join(IndeedJobLink, IndeedJobLink.job_id == Job.id)
        .filter(
            IndeedJobLink.owner_sub == owner_sub,
            IndeedJobLink.sourced_posting_id == sourced_posting_id,
            Job.owner_sub == owner_sub,
        )
        .order_by(IndeedJobLink.created_at.asc())
        .first()
    )


def resolve_job(
    db: Session,
    *,
    owner_sub: str,
    explicit_job_id: str | None,
    metadata: dict | None,
) -> Job | None:
    """Resolve only an explicit owned job or one unambiguous owned title."""
    if explicit_job_id:
        return jobs_repository.get_job(db, explicit_job_id, owner_sub=owner_sub)

    metadata = metadata or {}
    jobs = jobs_repository.list_jobs(db, owner_sub=owner_sub)
    extracted_title = _normalize(metadata.get("job_title"))
    if extracted_title:
        exact_matches = [job for job in jobs if _normalize(job.title) == extracted_title]
        if len(exact_matches) == 1:
            return exact_matches[0]
        if len(exact_matches) > 1:
            return None

    subject = _normalize(metadata.get("subject"))
    if not subject:
        return None
    matches = []
    for job in jobs:
        normalized_title = _normalize(job.title)
        if normalized_title and normalized_title in subject:
            matches.append(job)
    return matches[0] if len(matches) == 1 else None


def resolve_or_create_indeed_job(
    db: Session,
    *,
    owner_sub: str,
    metadata: dict | None,
) -> Job | None:
    """Resolve an Indeed vacancy that already exists locally; never create one.

    Indeed Employers vacancy synchronization owns provider identity. Gmail may
    use a strong already-linked posting id or a unique local title fallback, but
    it never creates a Job or an IndeedJobLink.
    """
    metadata = metadata or {}
    raw_title = " ".join(str(metadata.get("job_title") or "").split()).strip()
    if not raw_title:
        return None

    discovery_key = indeed_discovery_key(metadata)
    if discovery_key:
        winner = _job_by_discovery_key(
            db,
            owner_sub=owner_sub,
            discovery_key=discovery_key,
        )
        if winner is not None:
            return winner

    external_job_id = str(metadata.get("external_job_id") or "").strip() or None
    if external_job_id:
        linked = _job_by_sourced_posting_id(
            db,
            owner_sub=owner_sub,
            sourced_posting_id=external_job_id,
        )
        if linked is not None:
            return linked

    return resolve_job(
        db,
        owner_sub=owner_sub,
        explicit_job_id=None,
        metadata=metadata,
    )
