"""Recovery contract for expired Gmail history cursors."""

from types import SimpleNamespace

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.domains.candidate_ingestion import repository
from app.domains.candidate_ingestion.mailbox_sync import sync_gmail_mailbox
from app.integrations.email_ingestion.gmail import GmailHistoryExpired


class FakeStorage:
    def store_source_document(self, *, event_id, attachment_id, filename, data, content_type):
        return f"candidate-ingestion/{event_id}/{attachment_id}/{filename}"


class ExpiredHistoryMailbox:
    def __init__(self):
        self.full_scans = 0
        self.history_scans = 0

    def get_profile(self):
        return SimpleNamespace(email_address="personal@example.com", history_id="200")

    def list_history(self, *, start_history_id, page_token=None, max_results=100):
        self.history_scans += 1
        assert start_history_id == "100"
        raise GmailHistoryExpired("GMAIL_HISTORY_EXPIRED")

    def list_messages(self, *, page_token=None, max_results=100):
        self.full_scans += 1
        return SimpleNamespace(messages=[{"id": "gmail-2"}], next_page_token=None)

    def get_message(self, message_id):
        return {
            "id": message_id,
            "threadId": f"thread-{message_id}",
            "historyId": "200",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Indeed <alerts@indeed.com>"},
                    {"name": "Subject", "value": "New application"},
                ],
                "parts": [
                    {
                        "filename": "candidate.pdf",
                        "mimeType": "application/pdf",
                        "body": {"attachmentId": "a-1", "size": 7},
                    }
                ],
            },
        }

    def get_attachment(self, message_id, attachment_id):
        return b"pdfdata"


def test_expired_history_cursor_falls_back_to_idempotent_full_sync():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    mailbox = ExpiredHistoryMailbox()
    try:
        with Session(engine) as db:
            repository.upsert_cursor(
                db,
                owner_sub="owner-1",
                source="EMAIL",
                provider="INDEED",
                source_account="personal@example.com",
                cursor_value="100",
            )
            db.commit()

            result = sync_gmail_mailbox(
                db,
                owner_sub="owner-1",
                provider="INDEED",
                mailbox_client=mailbox,
                allowed_senders=("alerts@indeed.com",),
                storage=FakeStorage(),
            )

            assert result.mode == "FULL_RECOVERY"
            assert result.cursor_value == "200"
            assert result.created == 1
            assert mailbox.history_scans == 1
            assert mailbox.full_scans == 1
            cursor = repository.get_cursor(
                db,
                owner_sub="owner-1",
                source="EMAIL",
                provider="INDEED",
                source_account="personal@example.com",
            )
            assert cursor.cursor_value == "200"
    finally:
        engine.dispose()


def test_gmail_client_maps_history_404_to_expired_cursor(monkeypatch):
    from app.config import GmailSettings
    from app.integrations.email_ingestion.gmail import GmailClient

    class FakeHttp:
        def get(self, *args, **kwargs):
            request = httpx.Request("GET", "https://gmail.invalid/history")
            response = httpx.Response(404, request=request)
            return response

    settings = GmailSettings(
        enabled=True,
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
        user_id="me",
        query="has:attachment",
        allowed_senders=(),
        ingestion_provider="INDEED",
        scope="https://www.googleapis.com/auth/gmail.readonly",
        token_url="https://oauth2.googleapis.com/token",
        api_base_url="https://gmail.googleapis.com/gmail/v1",
        request_timeout_seconds=15,
    )
    client = GmailClient(settings, http_client=FakeHttp())
    monkeypatch.setattr(client, "get_access_token", lambda: "access")

    try:
        client.list_history(start_history_id="100")
    except GmailHistoryExpired:
        pass
    else:
        raise AssertionError("expected GmailHistoryExpired")
