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
    """Resolve or create one owner-scoped Indeed vacancy idempotently.

    Strong external posting identifiers win. When Indeed does not expose one,
    a canonicalized title is used as a deterministic fallback discovery key.
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

        # A previous notification may have exposed only the title. If that
        # fallback link still has no posting id, enrich it instead of creating
        # a duplicate when Indeed later reveals the strong identifier.
        title_key = f"title:{_canonical_title_key(raw_title)}"
        title_linked = _job_by_discovery_key(
            db,
            owner_sub=owner_sub,
            discovery_key=title_key,
        )
        if title_linked is not None:
            title_link = (
                db.query(IndeedJobLink)
                .filter(IndeedJobLink.job_id == title_linked.id)
                .with_for_update()
                .one_or_none()
            )
            if title_link is not None:
                if title_link.sourced_posting_id == external_job_id:
                    return title_linked
                if not title_link.sourced_posting_id:
                    savepoint = db.begin_nested()
                    try:
                        title_link.sourced_posting_id = external_job_id
                        db.flush()
                        savepoint.commit()
                        return title_linked
                    except IntegrityError:
                        savepoint.rollback()
                        linked = _job_by_sourced_posting_id(
                            db,
                            owner_sub=owner_sub,
                            sourced_posting_id=external_job_id,
                        )
                        if linked is not None:
                            return linked
                        raise

        # A stable posting id represents a distinct Indeed vacancy. Do not merge
        # it with another posting merely because the visible titles are equal.
        resolved = None
    else:
        resolved = resolve_job(
            db,
            owner_sub=owner_sub,
            explicit_job_id=None,
            metadata=metadata,
        )
        if resolved is not None:
            return _ensure_discovery_link(
                db,
                job=resolved,
                owner_sub=owner_sub,
                discovery_key=discovery_key,
                external_job_id=None,
                auto_created=False,
            )

    savepoint = db.begin_nested()
    try:
        job = Job(
            title=raw_title,
            description=None,
            owner_sub=owner_sub,
            evaluation_version=1,
            evaluation_profile={},
        )
        db.add(job)
        db.flush()
        _ensure_discovery_link(
            db,
            job=job,
            owner_sub=owner_sub,
            discovery_key=discovery_key,
            external_job_id=external_job_id,
            auto_created=True,
        )
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
