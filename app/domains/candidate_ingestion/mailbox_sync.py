"""Durable Gmail mailbox synchronization into the Candidate Ingestion Core."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.domains.candidate_ingestion import repository
from app.domains.candidate_ingestion.email_service import ingest_gmail_message
from app.integrations.email_ingestion.parser import (
    EmailSenderNotAllowed,
    InvalidEmailMessage,
)


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


def _full_scan(mailbox_client, *, max_results: int) -> list[str]:
    message_ids: list[str] = []
    page_token: str | None = None
    while True:
        page = mailbox_client.list_messages(
            page_token=page_token,
            max_results=max_results,
        )
        message_ids.extend(
            str(item.get("id") or "").strip()
            for item in page.messages
            if isinstance(item, dict)
        )
        page_token = page.next_page_token
        if not page_token:
            return _unique_message_ids(message_ids)


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


def sync_gmail_mailbox(
    db: Session,
    *,
    owner_sub: str,
    provider: str,
    mailbox_client,
    allowed_senders: tuple[str, ...] = (),
    storage=None,
    max_results: int = 100,
) -> GmailMailboxSyncResult:
    """Run one full or incremental Gmail sync and advance its cursor atomically last."""
    normalized_provider = str(provider or "").strip().upper()
    if not normalized_provider:
        raise ValueError("INGESTION_PROVIDER_REQUIRED")

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
        message_ids = _full_scan(mailbox_client, max_results=max_results)
        next_cursor_value = baseline_history_id
    else:
        mode = "INCREMENTAL"
        message_ids, next_cursor_value = _incremental_scan(
            mailbox_client,
            start_history_id=str(cursor.cursor_value),
            max_results=max_results,
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
