"""Composition layer for the configurable Gmail candidate-ingestion adapter."""

from __future__ import annotations

from dataclasses import asdict

import httpx
from sqlalchemy.orm import Session

from app.config import GmailSettings, get_gmail_settings
from app.domains.candidate_ingestion.mailbox_sync import sync_gmail_mailbox
from app.integrations.email_ingestion.gmail import GmailClient


class GmailDisabled(RuntimeError):
    pass


class GmailNotConfigured(RuntimeError):
    pass


class GmailRemoteError(RuntimeError):
    pass


def integration_status(*, settings: GmailSettings | None = None) -> dict:
    current = settings or get_gmail_settings()
    return {
        "enabled": current.enabled,
        "configured": current.configured,
        "provider": current.ingestion_provider,
    }


def sync_mailbox(
    db: Session,
    *,
    owner_sub: str,
    settings: GmailSettings | None = None,
    mailbox_client=None,
    storage=None,
) -> dict:
    """Run one authenticated Gmail sync without exposing OAuth credentials."""
    current = settings or get_gmail_settings()
    if not current.enabled:
        raise GmailDisabled("Gmail ingestion is disabled.")
    if not current.configured:
        raise GmailNotConfigured("Gmail OAuth is not configured.")

    client = mailbox_client or GmailClient(current)
    try:
        result = sync_gmail_mailbox(
            db,
            owner_sub=owner_sub,
            provider=current.ingestion_provider,
            mailbox_client=client,
            allowed_senders=current.allowed_senders,
            storage=storage,
        )
        return asdict(result)
    except httpx.HTTPError as exc:
        raise GmailRemoteError("Gmail API is unavailable.") from exc
    except RuntimeError as exc:
        code = str(exc)
        if code == "GMAIL_NOT_CONFIGURED":
            raise GmailNotConfigured("Gmail OAuth is not configured.") from exc
        if code.startswith("GMAIL_"):
            raise GmailRemoteError("Gmail API request failed.") from exc
        raise
