"""Deterministic tenant-scoped job resolution for candidate ingestion."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.domains.jobs import repository as jobs_repository
from app.models import Job


def _normalize(value: str | None) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def resolve_job(
    db: Session,
    *,
    owner_sub: str,
    explicit_job_id: str | None,
    metadata: dict | None,
) -> Job | None:
    """Resolve only an explicit owned job or one unambiguous title in metadata."""
    if explicit_job_id:
        return jobs_repository.get_job(
            db,
            explicit_job_id,
            owner_sub=owner_sub,
        )

    subject = _normalize((metadata or {}).get("subject"))
    if not subject:
        return None

    matches: list[Job] = []
    for job in jobs_repository.list_jobs(db, owner_sub=owner_sub):
        normalized_title = _normalize(job.title)
        if normalized_title and normalized_title in subject:
            matches.append(job)

    if len(matches) != 1:
        return None
    return matches[0]
