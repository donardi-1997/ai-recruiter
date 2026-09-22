"""Retrieve Candidates ingestion into the existing Asiati Talent candidate model."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.config import IndeedSettings
from app.domains.candidate_imports import repository as identity_repository
from app.domains.candidate_imports import rules as identity_rules
from app.domains.candidate_imports.exceptions import IdentityConflict
from app.domains.candidates import repository as candidates_repository
from app.domains.indeed import repository, resume_repository
from app.domains.indeed.client import IndeedClient
from app.domains.indeed.dispositions import queue_disposition_for_application
from app.infrastructure.imports import queue

logger = logging.getLogger(__name__)


def _parse_provider_datetime(value) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


FETCH_ASSETS = """
mutation FetchAssets($input: FetchAssetsAtsSyncCandidateSyncInput) {
  atsSyncCandidateSync {
    fetchAssets(input: $input) {
      token
      assets {
        id
        metadata {
          stagedAt
          stagedTest
          employerIdentifier
          completeSourceAttribution { enumKey name }
        }
        ... on AtsSyncCandidateSyncInterestedCandidateAsset {
          contact {
            candidate {
              email
              location
              name
              phone
              resume { pdf { name url } }
            }
            job { sourcedPostingId }
            tracking { recruiterEmail }
          }
        }
      }
    }
  }
}
"""


def _resolve_or_create_candidate(
    db,
    *,
    owner_sub: str,
    name: str,
    email: str | None,
    phone: str | None,
    source_name: str | None,
):
    normalized_email = identity_rules.normalize_email(email) if email else None
    normalized_phone = identity_rules.normalize_phone(phone) if phone else None
    matches: dict[str, str] = {}

    if normalized_email:
        identity = identity_repository.find_identity(
            db,
            owner_sub=owner_sub,
            kind="EMAIL",
            value=normalized_email,
        )
        if identity is not None:
            matches["EMAIL"] = identity.candidate_id

        legacy = identity_repository.find_legacy_candidates_by_normalized_email(
            db,
            owner_sub=owner_sub,
            normalized_email=normalized_email,
        )
        if len(legacy) > 1:
            raise IdentityConflict("IDENTITY_CONFLICT")
        if legacy:
            matches["LEGACY_EMAIL"] = legacy[0].id

    if normalized_phone:
        identity = identity_repository.find_identity(
            db,
            owner_sub=owner_sub,
            kind="PHONE",
            value=normalized_phone,
        )
        if identity is not None:
            matches["PHONE"] = identity.candidate_id

    candidate_id = identity_rules.resolve_identity_candidates(matches)
    if candidate_id:
        candidate = candidates_repository.get_candidate(
            db,
            candidate_id,
            owner_sub=owner_sub,
        )
        if candidate is None:
            raise IdentityConflict("IDENTITY_CONFLICT")
        outcome = "REUSED"
        if not candidate.email and normalized_email:
            candidate.email = normalized_email
    else:
        candidate = candidates_repository.create_candidate_pending(
            db,
            name=name,
            email=normalized_email,
            metadata={"source": source_name or "Indeed"},
            owner_sub=owner_sub,
        )
        outcome = "CREATED"

    metadata = dict(candidate.metadata_ or {})
    metadata.setdefault("source", source_name or "Indeed")
    candidate.metadata_ = metadata

    if normalized_email:
        identity_repository.attach_identity(
            db,
            owner_sub=owner_sub,
            candidate_id=candidate.id,
            kind="EMAIL",
            value=normalized_email,
        )
    if normalized_phone:
        identity_repository.attach_identity(
            db,
            owner_sub=owner_sub,
            candidate_id=candidate.id,
            kind="PHONE",
            value=normalized_phone,
        )
    return candidate, outcome


def _process_asset(db, *, owner_sub: str, asset: dict) -> str:
    asset_id = str(asset.get("id") or "").strip()
    if not asset_id:
        return "SKIPPED"

    existing = repository.get_candidate_link_by_asset(
        db,
        owner_sub=owner_sub,
        asset_id=asset_id,
    )
    if existing is not None:
        if existing.resume_url:
            resume_repository.get_or_create_resume_ingestion(
                db,
                owner_sub=owner_sub,
                candidate_link_id=existing.id,
            )
        return "REUSED"

    contact = asset.get("contact")
    if not isinstance(contact, dict):
        # Indeed can add asset types. Unknown assets are intentionally skipped.
        return "SKIPPED"

    candidate_data = contact.get("candidate") or {}
    job_data = contact.get("job") or {}
    name = str(candidate_data.get("name") or "").strip()
    sourced_posting_id = str(job_data.get("sourcedPostingId") or "").strip()
    if not name or not sourced_posting_id:
        return "SKIPPED"

    job_link = repository.get_job_link_by_sourced_posting(
        db,
        owner_sub=owner_sub,
        sourced_posting_id=sourced_posting_id,
    )
    if job_link is None:
        return "SKIPPED"

    metadata = asset.get("metadata") or {}
    attribution = metadata.get("completeSourceAttribution") or {}
    source_name = attribution.get("name") or "Indeed"
    resume_pdf = ((candidate_data.get("resume") or {}).get("pdf") or {})

    candidate, outcome = _resolve_or_create_candidate(
        db,
        owner_sub=owner_sub,
        name=name,
        email=candidate_data.get("email"),
        phone=candidate_data.get("phone"),
        source_name=source_name,
    )
    candidate_metadata = dict(candidate.metadata_ or {})
    candidate_metadata["source"] = "Indeed"
    candidate_metadata["source_name"] = source_name
    candidate_metadata["indeed_staged_test"] = bool(metadata.get("stagedTest"))
    if resume_pdf.get("name"):
        candidate_metadata["resume_name"] = resume_pdf.get("name")
    candidate.metadata_ = candidate_metadata

    assignment = candidates_repository.ensure_candidate_assigned_to_job(
        db,
        job_id=job_link.job_id,
        candidate_id=candidate.id,
    )
    db.flush()

    link = repository.create_candidate_link(
        db,
        owner_sub=owner_sub,
        candidate_id=candidate.id,
        job_id=job_link.job_id,
        asset_id=asset_id,
        employer_identifier=metadata.get("employerIdentifier"),
        source_enum_key=attribution.get("enumKey"),
        source_name=source_name,
        sourced_posting_id=sourced_posting_id,
        resume_name=resume_pdf.get("name"),
        resume_url=resume_pdf.get("url"),
        staged_test=bool(metadata.get("stagedTest")),
        staged_at=_parse_provider_datetime(metadata.get("stagedAt")),
    )
    if link.resume_url:
        resume_repository.get_or_create_resume_ingestion(
            db,
            owner_sub=owner_sub,
            candidate_link_id=link.id,
        )
    queue_disposition_for_application(
        db,
        owner_sub=owner_sub,
        candidate_link=link,
        local_status=assignment.application_status,
        status_changed_at=assignment.status_changed_at,
    )
    return outcome


def _dispatch_resume_tasks(db, *, owner_sub: str) -> int:
    """Best-effort dispatch after the candidate batch is durably committed."""
    dispatched = 0
    tasks = resume_repository.list_undispatched_resume_ingestions(
        db,
        owner_sub=owner_sub,
    )
    for task in tasks:
        try:
            queue.send_indeed_resume_ingestion(task.id)
        except Exception:
            db.rollback()
            logger.exception("Indeed resume dispatch failed for task %s", task.id)
            continue
        task.queue_dispatched_at = datetime.now(timezone.utc)
        db.commit()
        dispatched += 1
    return dispatched


def fetch_candidate_assets(
    db,
    *,
    owner_sub: str,
    settings: IndeedSettings,
    client: IndeedClient | None = None,
    limit: int = 25,
) -> dict:
    bounded_limit = min(max(int(limit), 1), 100)
    state = repository.get_or_create_candidate_sync_state(db, owner_sub)
    previous_token = state.ack_token
    variables = {"input": {"limit": bounded_limit}}
    if previous_token:
        variables["input"]["token"] = previous_token

    try:
        provider = client or IndeedClient(settings, include_employer=False)
        data = provider.execute(FETCH_ASSETS, variables)
        payload = data.get("atsSyncCandidateSync", {}).get("fetchAssets", {})
        assets = payload.get("assets") or []
        next_token = payload.get("token")
        now = datetime.now(timezone.utc)

        # A successful fetch carrying the previous token acknowledges the
        # previously persisted batch before the current batch is processed.
        if previous_token:
            repository.mark_unacknowledged_links_acknowledged(
                db,
                owner_sub=owner_sub,
                acknowledged_at=now,
            )
            state.last_ack_at = now

        counts = {"CREATED": 0, "REUSED": 0, "SKIPPED": 0}
        for asset in assets:
            outcome = _process_asset(db, owner_sub=owner_sub, asset=asset)
            counts[outcome] += 1

        state.ack_token = next_token or None
        state.last_fetch_at = now
        state.last_error = None
        db.commit()

        # Candidate/provider state is already durable. Queue failures are
        # intentionally repairable and must not invalidate the successful
        # fetchAssets/acknowledgment transaction.
        _dispatch_resume_tasks(db, owner_sub=owner_sub)

        return {
            "fetched": len(assets),
            "created": counts["CREATED"],
            "reused": counts["REUSED"],
            "skipped": counts["SKIPPED"],
            "next_token_present": bool(next_token),
            "last_sync_at": now.isoformat(),
        }
    except Exception as exc:
        db.rollback()
        try:
            error_state = repository.get_or_create_candidate_sync_state(db, owner_sub)
            error_state.last_error = str(exc)[:2000]
            db.commit()
        except Exception:
            db.rollback()
        raise
