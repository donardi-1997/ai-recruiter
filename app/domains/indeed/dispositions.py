"""Indeed disposition mapping and durable outbound synchronization."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.config import IndeedSettings
from app.domains.indeed import repository
from app.domains.indeed.client import IndeedClient
from app.domains.indeed.exceptions import IndeedValidationError

LOCAL_TO_INDEED_STATUS = {
    "APPLIED": "NEW",
    "SCREENING": "POSITIVELY_SCREENED",
    "INTERVIEW": "INTERVIEW",
    "OFFER": "OFFER_MADE",
    "HIRED": "HIRED",
    "REJECTED": "NOT_SELECTED",
    "WITHDRAWN": "WITHDRAWN",
    "ON_HOLD": None,
}

SEND_DISPOSITIONS = """
mutation SendDispositions($input: SendPartnerDispositionInput!) {
  partnerDisposition {
    send(input: $input) {
      numberGoodDispositions
      failedDispositions {
        identifiedBy {
          indeedApplyID
          ittk
          universalApplyId
          alternateIdentifier {
            jobIdentifier { employerJobId }
            jobSeekerIdentifier { emailAddress }
          }
        }
        rationale
      }
    }
  }
}
"""


def map_local_status(status: str) -> str | None:
    normalized = (status or "").strip().upper()
    if normalized not in LOCAL_TO_INDEED_STATUS:
        raise IndeedValidationError(f"Unsupported application status: {status}")
    return LOCAL_TO_INDEED_STATUS[normalized]


def queue_disposition_for_application(
    db,
    *,
    owner_sub: str,
    candidate_link,
    local_status: str,
    status_changed_at: datetime,
):
    indeed_status = map_local_status(local_status)
    if indeed_status is None:
        return None
    return repository.queue_disposition_event(
        db,
        owner_sub=owner_sub,
        candidate_link_id=candidate_link.id,
        local_status=local_status,
        indeed_status=indeed_status,
        status_changed_at=status_changed_at,
    )


def build_identifier(db, *, owner_sub: str, candidate_link) -> dict:
    if candidate_link.indeed_apply_id:
        return {"indeedApplyID": candidate_link.indeed_apply_id}
    if candidate_link.ittk:
        return {"ittk": candidate_link.ittk}
    if candidate_link.universal_apply_id:
        return {"universalApplyId": candidate_link.universal_apply_id}

    job_link = repository.get_job_link(db, candidate_link.job_id, owner_sub)
    candidate = candidate_link.candidate
    if job_link and job_link.employer_job_id and candidate and candidate.email:
        return {
            "alternateIdentifier": {
                "jobIdentifier": {"employerJobId": job_link.employer_job_id},
                "jobSeekerIdentifier": {"emailAddress": candidate.email},
            }
        }
    raise IndeedValidationError(
        "No valid Indeed disposition identifier is available for this application"
    )


def _identifier_key(identifier: dict) -> str:
    return json.dumps(identifier, sort_keys=True, separators=(",", ":"))


def _event_input(db, *, owner_sub: str, event, ats_name: str) -> tuple[dict, str]:
    identifier = build_identifier(
        db,
        owner_sub=owner_sub,
        candidate_link=event.candidate_link,
    )
    payload = {
        "identifiedBy": identifier,
        "dispositionStatus": event.indeed_status,
        "rawDispositionStatus": event.local_status,
        "atsName": ats_name,
        "statusChangeDateTime": event.status_changed_at.isoformat(),
    }
    source_name = event.candidate_link.source_name
    if source_name:
        payload["applicationSourceName"] = source_name
    return payload, _identifier_key(identifier)


def sync_dispositions(
    db,
    *,
    owner_sub: str,
    settings: IndeedSettings,
    client: IndeedClient | None = None,
    limit: int = 25,
) -> dict:
    events = repository.list_disposition_events_for_sync(
        db,
        owner_sub=owner_sub,
        limit=limit,
    )
    if not events:
        return {"selected": 0, "sent": 0, "failed": 0}

    request_items = []
    event_by_identifier: dict[str, object] = {}
    locally_failed = []
    for event in events:
        try:
            item, key = _event_input(
                db,
                owner_sub=owner_sub,
                event=event,
                ats_name=settings.source_name or "Asiati Talent",
            )
            request_items.append(item)
            event_by_identifier[key] = event
        except IndeedValidationError as exc:
            event.attempt_count += 1
            repository.mark_disposition_failed(event, error=str(exc))
            locally_failed.append(event)

    if not request_items:
        db.commit()
        return {
            "selected": len(events),
            "sent": 0,
            "failed": len(locally_failed),
        }

    network_events = list(event_by_identifier.values())
    repository.mark_disposition_attempted(network_events)
    try:
        data = (client or IndeedClient(settings)).execute(
            SEND_DISPOSITIONS,
            {"input": {"dispositions": request_items}},
        )
        result = data.get("partnerDisposition", {}).get("send", {})
        failed_payloads = result.get("failedDispositions") or []

        now = datetime.now(timezone.utc)
        for event in network_events:
            repository.mark_disposition_sent(event, sent_at=now)

        provider_failed = 0
        for failed in failed_payloads:
            key = _identifier_key(failed.get("identifiedBy") or {})
            event = event_by_identifier.get(key)
            if event is None:
                continue
            provider_failed += 1
            repository.mark_disposition_failed(
                event,
                error=str(failed.get("rationale") or "Indeed rejected disposition"),
            )
            event.sent_at = None

        db.commit()
        return {
            "selected": len(events),
            "sent": len(network_events) - provider_failed,
            "failed": len(locally_failed) + provider_failed,
        }
    except Exception as exc:
        for event in network_events:
            repository.mark_disposition_failed(event, error=str(exc))
        db.commit()
        raise
