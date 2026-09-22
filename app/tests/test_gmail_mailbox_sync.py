"""Contracts for Gmail full/incremental mailbox synchronization."""

import base64
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.domains.candidate_ingestion import repository
from app.domains.candidate_ingestion.mailbox_sync import sync_gmail_mailbox
from app.domains.candidate_ingestion.models import IndeedEmailResumeTask
from app.models import IndeedJobLink, Job


class FakeStorage:
    def __init__(self):
        self.calls = []

    def store_source_document(self, *, event_id, attachment_id, filename, data, content_type):
        self.calls.append((event_id, attachment_id, filename, data, content_type))
        return f"candidate-ingestion/{event_id}/{attachment_id}/{filename}"


class FakeMailboxClient:
    def __init__(
        self,
        *,
        email_address,
        profile_history_id,
        full_message_ids=(),
        history_message_ids=(),
        next_history_id=None,
    ):
        self.email_address = email_address
        self.profile_history_id = profile_history_id
        self.full_message_ids = tuple(full_message_ids)
        self.history_message_ids = tuple(history_message_ids)
        self.next_history_id = next_history_id or profile_history_id
        self.list_messages_calls = 0
        self.list_history_calls = []

    def get_profile(self):
        return SimpleNamespace(email_address=self.email_address, history_id=self.profile_history_id)

    def list_messages(self, *, page_token=None, max_results=100):
        self.list_messages_calls += 1
        assert page_token is None
        return SimpleNamespace(
            messages=[{"id": message_id} for message_id in self.full_message_ids],
            next_page_token=None,
        )

    def list_history(self, *, start_history_id, page_token=None, max_results=100):
        self.list_history_calls.append(start_history_id)
        return SimpleNamespace(
            message_ids=self.history_message_ids,
            history_id=self.next_history_id,
            next_page_token=None,
        )

    def get_message(self, message_id):
        return {
            "id": message_id,
            "threadId": f"thread-{message_id}",
            "historyId": self.profile_history_id,
            "payload": {
                "headers": [
                    {"name": "From", "value": "Indeed <alerts@indeed.com>"},
                    {"name": "Subject", "value": "New application"},
                ],
                "parts": [
                    {
                        "filename": f"{message_id}.pdf",
                        "mimeType": "application/pdf",
                        "body": {"attachmentId": f"attachment-{message_id}", "size": 7},
                    }
                ],
            },
        }

    def get_attachment(self, message_id, attachment_id):
        return b"pdfdata"


class FakeIndeedLinkMailbox(FakeMailboxClient):
    def get_message(self, message_id):
        html = (
            "<html><body>"
            "<p>Ana Perez se postulo para Country Manager Chile</p>"
            '<a href="https://employers.indeed.com/resume/ana-perez">Ver CV</a>'
            "</body></html>"
        )
        data = base64.urlsafe_b64encode(html.encode("utf-8")).decode("ascii").rstrip("=")
        return {
            "id": message_id,
            "threadId": f"thread-{message_id}",
            "historyId": self.profile_history_id,
            "payload": {
                "mimeType": "text/html",
                "headers": [
                    {"name": "From", "value": "Indeed <conversation-abc@indeedemail.com>"},
                    {"name": "Subject", "value": "Ana Perez se postulo"},
                ],
                "body": {"data": data},
            },
        }


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def test_first_sync_uses_discovered_mailbox_identity_and_persists_baseline_cursor():
    engine, db = _db()
    storage = FakeStorage()
    client = FakeMailboxClient(
        email_address="Personal@Example.com",
        profile_history_id="100",
        full_message_ids=("gmail-1",),
    )
    try:
        result = sync_gmail_mailbox(
            db,
            owner_sub="owner-1",
            provider="INDEED",
            mailbox_client=client,
            allowed_senders=("alerts@indeed.com",),
            storage=storage,
        )
        assert result.mode == "FULL"
        assert result.source_account == "personal@example.com"
        assert result.discovered == 1
        assert result.created == 1
        assert result.cursor_value == "100"
        cursor = repository.get_cursor(
            db,
            owner_sub="owner-1",
            source="EMAIL",
            provider="INDEED",
            source_account="personal@example.com",
        )
        assert cursor is not None
        assert cursor.cursor_value == "100"
        event = repository.get_event_by_external_id(
            db,
            owner_sub="owner-1",
            source="EMAIL",
            provider="INDEED",
            source_account="personal@example.com",
            external_id="gmail-1",
        )
        assert event is not None
        assert event.source_account == "personal@example.com"
    finally:
        db.close()
        engine.dispose()


def test_indeed_link_notification_advances_cursor_and_creates_download_task_for_synced_job():
    engine, db = _db()
    client = FakeIndeedLinkMailbox(
        email_address="katherine@example.com",
        profile_history_id="700",
        full_message_ids=("gmail-indeed-1",),
    )
    try:
        job = Job(
            title="Country Manager Chile",
            description="Descripción completa",
            indeed_description="Descripción completa",
            active_description_source="indeed",
            owner_sub="owner-1",
        )
        db.add(job)
        db.flush()
        db.add(
            IndeedJobLink(
                job_id=job.id,
                owner_sub="owner-1",
                discovery_key=f"employer-ui:seed-{job.id}",
                external_status={"origin": "EMPLOYER_UI"},
            )
        )
        db.commit()
        result = sync_gmail_mailbox(
            db,
            owner_sub="owner-1",
            provider="INDEED",
            mailbox_client=client,
        )
        assert result.mode == "FULL"
        assert result.discovered == 1
        assert result.created == 1
        assert result.needs_review == 0
        assert result.skipped == 0
        assert result.cursor_value == "700"
        assert db.query(IndeedEmailResumeTask).count() == 1
        task = db.query(IndeedEmailResumeTask).one()
        assert task.status == "WAITING_DOWNLOAD"
        assert task.candidate_name == "Ana Perez"
        assert task.job_id is not None
    finally:
        db.close()
        engine.dispose()


def test_next_sync_uses_history_cursor_instead_of_rescanning_mailbox():
    engine, db = _db()
    storage = FakeStorage()
    try:
        initial = FakeMailboxClient(
            email_address="personal@example.com",
            profile_history_id="100",
            full_message_ids=("gmail-1",),
        )
        sync_gmail_mailbox(
            db,
            owner_sub="owner-1",
            provider="INDEED",
            mailbox_client=initial,
            allowed_senders=("alerts@indeed.com",),
            storage=storage,
        )
        incremental = FakeMailboxClient(
            email_address="personal@example.com",
            profile_history_id="120",
            history_message_ids=("gmail-2",),
            next_history_id="120",
        )
        result = sync_gmail_mailbox(
            db,
            owner_sub="owner-1",
            provider="INDEED",
            mailbox_client=incremental,
            allowed_senders=("alerts@indeed.com",),
            storage=storage,
        )
        assert result.mode == "INCREMENTAL"
        assert incremental.list_messages_calls == 0
        assert incremental.list_history_calls == ["100"]
        assert result.cursor_value == "120"
        assert result.created == 1
    finally:
        db.close()
        engine.dispose()


def test_authorizing_corporate_mailbox_gets_independent_full_sync_and_cursor():
    engine, db = _db()
    storage = FakeStorage()
    try:
        personal = FakeMailboxClient(
            email_address="personal@example.com",
            profile_history_id="100",
            full_message_ids=("gmail-1",),
        )
        corporate = FakeMailboxClient(
            email_address="talent@asiati.example",
            profile_history_id="900",
            full_message_ids=("gmail-1",),
        )
        sync_gmail_mailbox(
            db,
            owner_sub="owner-1",
            provider="INDEED",
            mailbox_client=personal,
            allowed_senders=("alerts@indeed.com",),
            storage=storage,
        )
        result = sync_gmail_mailbox(
            db,
            owner_sub="owner-1",
            provider="INDEED",
            mailbox_client=corporate,
            allowed_senders=("alerts@indeed.com",),
            storage=storage,
        )
        assert result.mode == "FULL"
        assert result.source_account == "talent@asiati.example"
        assert corporate.list_messages_calls == 1
        assert db.query(repository.CandidateIngestionEvent).count() == 2
        assert db.query(repository.CandidateIngestionCursor).count() == 2
    finally:
        db.close()
        engine.dispose()


class PagedMailboxClient(FakeMailboxClient):
    def __init__(self, *, email_address, profile_history_id, pages):
        super().__init__(email_address=email_address, profile_history_id=profile_history_id)
        self.pages = dict(pages)
        self.page_tokens = []

    def list_messages(self, *, page_token=None, max_results=100):
        self.list_messages_calls += 1
        self.page_tokens.append(page_token)
        messages, next_page_token = self.pages[page_token]
        return SimpleNamespace(
            messages=[{"id": message_id} for message_id in messages],
            next_page_token=next_page_token,
        )


def test_full_sync_bootstrap_is_batched_and_resumes_from_saved_page_token():
    engine, db = _db()
    storage = FakeStorage()
    client = PagedMailboxClient(
        email_address="personal@example.com",
        profile_history_id="100",
        pages={
            None: (("gmail-1", "gmail-2"), "page-2"),
            "page-2": (("gmail-3",), None),
        },
    )
    try:
        first = sync_gmail_mailbox(
            db,
            owner_sub="owner-1",
            provider="INDEED",
            mailbox_client=client,
            allowed_senders=("alerts@indeed.com",),
            storage=storage,
            max_results=2,
        )
        assert first.mode == "FULL"
        assert first.discovered == 2
        assert first.created == 2
        assert first.cursor_value.startswith("GMAIL_BOOTSTRAP_V1:")
        assert client.page_tokens == [None]

        second = sync_gmail_mailbox(
            db,
            owner_sub="owner-1",
            provider="INDEED",
            mailbox_client=client,
            allowed_senders=("alerts@indeed.com",),
            storage=storage,
            max_results=2,
        )
        assert second.mode == "FULL_CONTINUE"
        assert second.discovered == 1
        assert second.created == 1
        assert second.cursor_value == "100"
        assert client.page_tokens == [None, "page-2"]
        cursor = repository.get_cursor(
            db,
            owner_sub="owner-1",
            source="EMAIL",
            provider="INDEED",
            source_account="personal@example.com",
        )
        assert cursor.cursor_value == "100"
    finally:
        db.close()
        engine.dispose()


def test_bootstrap_finishes_on_original_history_baseline_then_incremental_catches_new_mail():
    engine, db = _db()
    storage = FakeStorage()
    paged = PagedMailboxClient(
        email_address="personal@example.com",
        profile_history_id="100",
        pages={
            None: (("gmail-1",), "page-2"),
            "page-2": (("gmail-2",), None),
        },
    )
    try:
        sync_gmail_mailbox(
            db,
            owner_sub="owner-1",
            provider="INDEED",
            mailbox_client=paged,
            allowed_senders=("alerts@indeed.com",),
            storage=storage,
            max_results=1,
        )
        paged.profile_history_id = "120"
        second = sync_gmail_mailbox(
            db,
            owner_sub="owner-1",
            provider="INDEED",
            mailbox_client=paged,
            allowed_senders=("alerts@indeed.com",),
            storage=storage,
            max_results=1,
        )
        assert second.cursor_value == "100"

        incremental = FakeMailboxClient(
            email_address="personal@example.com",
            profile_history_id="120",
            history_message_ids=("gmail-new",),
            next_history_id="120",
        )
        third = sync_gmail_mailbox(
            db,
            owner_sub="owner-1",
            provider="INDEED",
            mailbox_client=incremental,
            allowed_senders=("alerts@indeed.com",),
            storage=storage,
            max_results=20,
        )
        assert third.mode == "INCREMENTAL"
        assert incremental.list_history_calls == ["100"]
        assert third.created == 1
        assert third.cursor_value == "120"
    finally:
        db.close()
        engine.dispose()