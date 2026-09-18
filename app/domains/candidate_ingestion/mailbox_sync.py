"""Durable Gmail mailbox synchronization into the Candidate Ingestion Core."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.domains.candidate_ingestion import repository
from app.domains.candidate_ingestion.email_service import ingest_gmail_message
from app.integrations.email_ingestion.gmail import GmailHistoryExpired
from app.integrations.email_ingestion.parser import (
    EmailSenderNotAllowed,
    InvalidEmailMessage,
)


_BOOTSTRAP_CURSOR_PREFIX = "GMAIL_BOOTSTRAP_V1:"


@dataclass(frozen=True)
class GmailMailboxSyncResult:
    mode: str
    source_account: str
    discovered: int
    created: int
    existing: int
    needs_review: int
    skipped: int
    cursor_value: str


def _unique_message_ids(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        message_id = str(value or "").strip()
        if message_id and message_id not in seen:
            seen.add(message_id)
            result.append(message_id)
    return result


def _encode_bootstrap_cursor(*, baseline_history_id: str, page_token: str) -> str:
    payload = {
        "baseline_history_id": str(baseline_history_id),
        "page_token": str(page_token),
    }
    return _BOOTSTRAP_CURSOR_PREFIX + json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_bootstrap_cursor(value: str) -> tuple[str, str] | None:
    raw = str(value or "")
    if not raw.startswith(_BOOTSTRAP_CURSOR_PREFIX):
        return None
    try:
        payload = json.loads(raw[len(_BOOTSTRAP_CURSOR_PREFIX) :])
        baseline_history_id = str(payload["baseline_history_id"] or "").strip()
        page_token = str(payload["page_token"] or "").strip()
    except Exception as exc:
        raise ValueError("GMAIL_BOOTSTRAP_CURSOR_INVALID") from exc
    if not baseline_history_id or not page_token:
        raise ValueError("GMAIL_BOOTSTRAP_CURSOR_INVALID")
    return baseline_history_id, page_token


def _full_scan_page(
    mailbox_client,
    *,
    page_token: str | None,
    max_results: int,
) -> tuple[list[str], str | None]:
    page = mailbox_client.list_messages(
        page_token=page_token,
        max_results=max_results,
    )
    message_ids = _unique_message_ids(
        str(item.get("id") or "").strip()
        for item in page.messages
        if isinstance(item, dict)
    )
    next_page_token = str(page.next_page_token or "").strip() or None
    return message_ids, next_page_token


def _incremental_scan(
    mailbox_client,
    *,
    start_history_id: str,
    max_results: int,
) -> tuple[list[str], str]:
    message_ids: list[str] = []
    page_token: str | None = None
    latest_history_id = str(start_history_id)
    while True:
        page = mailbox_client.list_history(
            start_history_id=start_history_id,
            page_token=page_token,
            max_results=max_results,
        )
        message_ids.extend(page.message_ids)
        if page.history_id:
            latest_history_id = str(page.history_id)
        page_token = page.next_page_token
        if not page_token:
            return _unique_message_ids(message_ids), latest_history_id


def _next_full_cursor(
    *,
    baseline_history_id: str,
    next_page_token: str | None,
) -> str:
    if not next_page_token:
        return str(baseline_history_id)
    return _encode_bootstrap_cursor(
        baseline_history_id=baseline_history_id,
        page_token=next_page_token,
    )


def sync_gmail_mailbox(
    db: Session,
    *,
    owner_sub: str,
    provider: str,
    mailbox_client,
    allowed_senders: tuple[str, ...] = (),
    allowed_sender_domains: tuple[str, ...] = (),
    storage=None,
    max_results: int = 20,
) -> GmailMailboxSyncResult:
    """Run one Gmail sync while bounding initial/recovery full scans to one page.

    The first historical scan persists Gmail's page token together with the profile
    history id captured before the scan began. Subsequent calls continue page by page.
    Once the historical scan finishes, the cursor becomes that baseline history id so
    the next incremental sync catches messages that arrived during bootstrap.
    """
    normalized_provider = str(provider or "").strip().upper()
    if not normalized_provider:
        raise ValueError("INGESTION_PROVIDER_REQUIRED")

    bounded_max_results = max(1, min(int(max_results), 100))

    profile = mailbox_client.get_profile()
    source_account = str(profile.email_address or "").strip().casefold()
    baseline_history_id = str(profile.history_id or "").strip()
    if not source_account or not baseline_history_id:
        raise ValueError("GMAIL_PROFILE_INCOMPLETE")

    cursor = repository.get_cursor(
        db,
        owner_sub=owner_sub,
        source="EMAIL",
        provider=normalized_provider,
        source_account=source_account,
    )

    if cursor is None or not cursor.cursor_value:
        mode = "FULL"
        message_ids, next_page_token = _full_scan_page(
            mailbox_client,
            page_token=None,
            max_results=bounded_max_results,
        )
        next_cursor_value = _next_full_cursor(
            baseline_history_id=baseline_history_id,
            next_page_token=next_page_token,
        )
    else:
        cursor_value = str(cursor.cursor_value)
        bootstrap = _decode_bootstrap_cursor(cursor_value)
        if bootstrap is not None:
            stored_baseline_history_id, page_token = bootstrap
            mode = "FULL_CONTINUE"
            message_ids, next_page_token = _full_scan_page(
                mailbox_client,
                page_token=page_token,
                max_results=bounded_max_results,
            )
            next_cursor_value = _next_full_cursor(
                baseline_history_id=stored_baseline_history_id,
                next_page_token=next_page_token,
            )
        else:
            try:
                mode = "INCREMENTAL"
                message_ids, next_cursor_value = _incremental_scan(
                    mailbox_client,
                    start_history_id=cursor_value,
                    max_results=bounded_max_results,
                )
            except GmailHistoryExpired:
                # Recover stale history cursors with the same bounded full-scan
                # bootstrap. The captured profile history id becomes the incremental
                # baseline only after all recovery pages have been processed.
                mode = "FULL_RECOVERY"
                message_ids, next_page_token = _full_scan_page(
                    mailbox_client,
                    page_token=None,
                    max_results=bounded_max_results,
                )
                next_cursor_value = _next_full_cursor(
                    baseline_history_id=baseline_history_id,
                    next_page_token=next_page_token,
                )

    created = 0
    existing = 0
    needs_review = 0
    skipped = 0

    for message_id in message_ids:
        try:
            result = ingest_gmail_message(
                db,
                owner_sub=owner_sub,
                message_id=message_id,
                mailbox_client=mailbox_client,
                provider=normalized_provider,
                source_account=source_account,
                allowed_senders=allowed_senders,
                allowed_sender_domains=allowed_sender_domains,
                storage=storage,
            )
        except (EmailSenderNotAllowed, InvalidEmailMessage):
            # Incremental Gmail history is mailbox-wide. Unrelated/malformed messages
            # are intentionally ignored instead of blocking the durable cursor.
            skipped += 1
            continue

        if result.created:
            created += 1
        else:
            existing += 1
        if result.event.status == "NEEDS_REVIEW":
            needs_review += 1

    repository.upsert_cursor(
        db,
        owner_sub=owner_sub,
        source="EMAIL",
        provider=normalized_provider,
        source_account=source_account,
        cursor_value=next_cursor_value,
    )
    db.commit()

    return GmailMailboxSyncResult(
        mode=mode,
        source_account=source_account,
        discovered=len(message_ids),
        created=created,
        existing=existing,
        needs_review=needs_review,
        skipped=skipped,
        cursor_value=next_cursor_value,
    )
