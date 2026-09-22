"""Deterministic tenant-scoped job resolution for candidate ingestion."""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy.exc import IntegrityError
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


def _job_by_employer_ui_key(
    db: Session,
    *,
    owner_sub: str,
    external_job_id: str,
) -> Job | None:
    """Match the browser-synced job identity without overloading sourced_posting_id."""
    raw = str(external_job_id or "").strip()
    if not raw:
        return None
    keys = [f"employer-ui:{raw}"]
    folded = f"employer-ui:{raw.casefold()}"
    if folded not in keys:
        keys.append(folded)
    return (
        db.query(Job)
        .join(IndeedJobLink, IndeedJobLink.job_id == Job.id)
        .filter(
            IndeedJobLink.owner_sub == owner_sub,
            IndeedJobLink.discovery_key.in_(keys),
            Job.owner_sub == owner_sub,
        )
        .order_by(IndeedJobLink.created_at.asc())
        .first()
    )


def _linked_job_by_title(
    db: Session,
    *,
    owner_sub: str,
    job_title: str,
) -> Job | None:
    """Resolve a title only among vacancies already linked to Indeed."""
    target = _normalize(job_title)
    if not target:
        return None

    rows = (
        db.query(Job)
        .join(IndeedJobLink, IndeedJobLink.job_id == Job.id)
        .filter(
            Job.owner_sub == owner_sub,
            IndeedJobLink.owner_sub == owner_sub,
        )
        .all()
    )
    matches = {
        job.id: job
        for job in rows
        if _normalize(job.title) == target
    }
    if len(matches) != 1:
        return None
    return next(iter(matches.values()))


def _ensure_discovery_link(
    db: Session,
    *,
    job: Job,
    owner_sub: str,
    discovery_key: str,
    external_job_id: str | None,
    auto_created: bool,
) -> Job:
    existing = (
        db.query(IndeedJobLink)
        .filter(IndeedJobLink.job_id == job.id)
        .one_or_none()
    )
    if existing is not None:
        winner = _job_by_discovery_key(
            db,
            owner_sub=owner_sub,
            discovery_key=discovery_key,
        )
        if winner is not None and winner.id != job.id:
            return winner

        set_discovery_key = existing.discovery_key is None
        set_external_id = bool(external_job_id and not existing.sourced_posting_id)
        if not set_discovery_key and not set_external_id:
            return job

        savepoint = db.begin_nested()
        try:
            if set_discovery_key:
                existing.discovery_key = discovery_key
            if set_external_id:
                existing.sourced_posting_id = external_job_id
            db.flush()
            savepoint.commit()
            return job
        except IntegrityError:
            savepoint.rollback()
            winner = _job_by_discovery_key(
                db,
                owner_sub=owner_sub,
                discovery_key=discovery_key,
            )
            if winner is not None:
                return winner
            raise

    link = IndeedJobLink(
        job_id=job.id,
        owner_sub=owner_sub,
        discovery_key=discovery_key,
        sourced_posting_id=external_job_id,
        external_status={
            "origin": "EMAIL_AUTO_DISCOVERY" if auto_created else "EMAIL_DISCOVERY_LINKED",
            "auto_created": bool(auto_created),
        },
    )
    db.add(link)
    db.flush()
    return job


def resolve_job(
    db: Session,
    *,
    owner_sub: str,
    explicit_job_id: str | None,
    metadata: dict | None,
) -> Job | None:
    """Resolve only an explicit owned job or one unambiguous owned title."""
    if explicit_job_id:
        return jobs_repository.get_job(
            db,
            explicit_job_id,
            owner_sub=owner_sub,
        )

    metadata = metadata or {}
    jobs = jobs_repository.list_jobs(db, owner_sub=owner_sub)

    extracted_title = _normalize(metadata.get("job_title"))
    if extracted_title:
        exact_matches = [
            job for job in jobs if _normalize(job.title) == extracted_title
        ]
        if len(exact_matches) == 1:
            return exact_matches[0]
        if len(exact_matches) > 1:
            return None

    subject = _normalize(metadata.get("subject"))
    if not subject:
        return None

    matches: list[Job] = []
    for job in jobs:
        normalized_title = _normalize(job.title)
        if normalized_title and normalized_title in subject:
            matches.append(job)

    if len(matches) != 1:
        return None
    return matches[0]


def resolve_or_create_indeed_job(
    db: Session,
    *,
    owner_sub: str,
    metadata: dict | None,
) -> Job | None:
    """Resolve an Indeed vacancy that already exists locally; never create one.

    Indeed Employers vacancy synchronization is the canonical creation path.
    Gmail only discovers applications. Strong posting identifiers win, followed
    by a controlled title fallback restricted to vacancies already linked to
    Indeed. Unlinked manual vacancies are never adopted by Gmail.
    """
    metadata = metadata or {}
    raw_title = " ".join(str(metadata.get("job_title") or "").split()).strip()
    if not raw_title:
        return None

    discovery_key = indeed_discovery_key(metadata)
    if not discovery_key:
        return None

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
            return _ensure_discovery_link(
                db,
                job=linked,
                owner_sub=owner_sub,
                discovery_key=discovery_key,
                external_job_id=external_job_id,
                auto_created=False,
            )

        employer_ui_job = _job_by_employer_ui_key(
            db,
            owner_sub=owner_sub,
            external_job_id=external_job_id,
        )
        if employer_ui_job is not None:
            return employer_ui_job

    resolved = _linked_job_by_title(
        db,
        owner_sub=owner_sub,
        job_title=raw_title,
    )
    if resolved is None:
        return None

    return _ensure_discovery_link(
        db,
        job=resolved,
        owner_sub=owner_sub,
        discovery_key=discovery_key,
        external_job_id=external_job_id,
        auto_created=False,
    )