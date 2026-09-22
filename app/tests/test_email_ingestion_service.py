"""Contracts for durable Gmail -> Candidate Ingestion Core handoff."""

import base64
import importlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401 - register shared tables in Base metadata
from app.db import Base
from app.models import IndeedJobLink, Job


class FakeMailboxClient:
    def __init__(self, message, attachments):
        self.message = message
        self.attachments = attachments
        self.message_calls = 0
        self.attachment_calls = []

    def get_message(self, message_id):
        self.message_calls += 1
        assert message_id == self.message["id"]
        return self.message

    def get_attachment(self, message_id, attachment_id):
        self.attachment_calls.append((message_id, attachment_id))
        return self.attachments[attachment_id]


class FakeStorage:
    def __init__(self):
        self.calls = []

    def store_source_document(self, *, event_id, attachment_id, filename, data, content_type):
        self.calls.append(
            {
                "event_id": event_id,
                "attachment_id": attachment_id,
                "filename": filename,
                "data": data,
                "content_type": content_type,
            }
        )
        return f"candidate-ingestion/{event_id}/source/{attachment_id}/{filename}"


def _service_module():
    try:
        return importlib.import_module("app.domains.candidate_ingestion.email_service")
    except ModuleNotFoundError as exc:
        pytest.fail(f"email ingestion service is missing: {exc}")


def _message(*, include_attachment=True):
    parts = []
    if include_attachment:
        parts.append(
            {
                "filename": "candidate.pdf",
                "mimeType": "application/pdf",
                "body": {"attachmentId": "attachment-1", "size": 7},
            }
        )
    return {
        "id": "gmail-1",
        "threadId": "thread-1",
        "historyId": "55",
        "internalDate": "1789574400000",
        "payload": {
            "headers": [
                {"name": "From", "value": "Indeed <alerts@indeed.com>"},
                {"name": "Subject", "value": "New application for Country Manager Chile"},
            ],
            "parts": parts,
        },
    }


def _indeed_link_message():
    html = (
        "<html><body>"
        "<p>Ana Perez se postulo para Country Manager Chile</p>"
        '<a href="https://employers.indeed.com/resume/ana-perez">Ver CV</a>'
        "</body></html>"
    )
    data = base64.urlsafe_b64encode(html.encode("utf-8")).decode("ascii").rstrip("=")
    return {
        "id": "gmail-indeed-link",
        "threadId": "thread-indeed-link",
        "historyId": "77",
        "internalDate": "1789574400000",
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


def _seed_synced_job(db, *, owner_sub="owner-1"):
    job = Job(
        title="Country Manager Chile",
        description="Descripción original de Indeed",
        indeed_description="Descripción original de Indeed",
        active_description_source="indeed",
        owner_sub=owner_sub,
        evaluation_profile={},
    )
    db.add(job)
    db.flush()
    db.add(
        IndeedJobLink(
            job_id=job.id,
            owner_sub=owner_sub,
            discovery_key=f"employer-ui:seed-{job.id}",
            external_status={"origin": "EMPLOYER_UI"},
        )
    )
    db.commit()
    return job


def test_ingest_gmail_message_persists_event_document_hash_and_source_key():
    service = _service_module()
    engine, db = _db()
    mailbox = FakeMailboxClient(_message(), {"attachment-1": b"pdfdata"})
    storage = FakeStorage()
    try:
        result = service.ingest_gmail_message(
            db,
            owner_sub="owner-1",
            message_id="gmail-1",
            mailbox_client=mailbox,
            storage=storage,
            provider="INDEED",
            allowed_senders=("alerts@indeed.com",),
        )

        assert result.created is True
        assert result.event.source == "EMAIL"
        assert result.event.provider == "INDEED"
        assert result.event.external_id == "gmail-1"
        assert result.event.status == "STORED"
        assert result.event.job_id is None
        assert result.event.candidate_id is None
        assert result.event.raw_metadata["subject"] == "New application for Country Manager Chile"
        assert result.event.raw_metadata["sender"] == "alerts@indeed.com"
        assert len(result.event.documents) == 1
        document = result.event.documents[0]
        assert document.filename == "candidate.pdf"
        assert document.size_bytes == len(b"pdfdata")
        assert len(document.document_sha256) == 64
        assert document.source_s3_key.endswith("/attachment-1/candidate.pdf")
        assert document.status == "STORED"
        assert len(storage.calls) == 1
    finally:
        db.close()
        engine.dispose()


def test_repeated_gmail_message_is_idempotent_and_does_not_redownload_attachment():
    service = _service_module()
    engine, db = _db()
    mailbox = FakeMailboxClient(_message(), {"attachment-1": b"pdfdata"})
    storage = FakeStorage()
    try:
        first = service.ingest_gmail_message(
            db,
            owner_sub="owner-1",
            message_id="gmail-1",
            mailbox_client=mailbox,
            storage=storage,
            provider="INDEED",
            allowed_senders=("alerts@indeed.com",),
        )
        second = service.ingest_gmail_message(
            db,
            owner_sub="owner-1",
            message_id="gmail-1",
            mailbox_client=mailbox,
            storage=storage,
            provider="INDEED",
            allowed_senders=("alerts@indeed.com",),
        )

        assert first.event.id == second.event.id
        assert second.created is False
        assert mailbox.message_calls == 1
        assert mailbox.attachment_calls == [("gmail-1", "attachment-1")]
        assert len(storage.calls) == 1
    finally:
        db.close()
        engine.dispose()


def test_email_without_supported_resume_is_durable_needs_review_not_silently_dropped():
    service = _service_module()
    engine, db = _db()
    mailbox = FakeMailboxClient(_message(include_attachment=False), {})
    storage = FakeStorage()
    try:
        result = service.ingest_gmail_message(
            db,
            owner_sub="owner-1",
            message_id="gmail-1",
            mailbox_client=mailbox,
            storage=storage,
            provider="INDEED",
            allowed_senders=("alerts@indeed.com",),
        )

        assert result.created is True
        assert result.event.status == "NEEDS_REVIEW"
        assert result.event.last_error_code == "RESUME_ATTACHMENT_MISSING"
        assert result.event.documents == []
        assert storage.calls == []
    finally:
        db.close()
        engine.dispose()


def test_indeed_notification_without_attachment_creates_download_task():
    service = _service_module()
    engine, db = _db()
    mailbox = FakeMailboxClient(_indeed_link_message(), {})
    storage = FakeStorage()
    try:
        _seed_synced_job(db)
        result = service.ingest_gmail_message(
            db,
            owner_sub="owner-1",
            message_id="gmail-indeed-link",
            mailbox_client=mailbox,
            storage=storage,
            provider="INDEED",
            source_account="katherine@example.com",
        )

        assert result.created is True
        assert result.event.status == "RECEIVED"
        assert result.event.last_error_code == "RESUME_DOWNLOAD_PENDING"
        assert result.event.indeed_email_resume_task is not None
        assert result.event.indeed_email_resume_task.status == "WAITING_DOWNLOAD"
        assert result.event.documents == []
        assert mailbox.attachment_calls == []
        assert storage.calls == []
    finally:
        db.close()
        engine.dispose()


def test_same_gmail_message_id_is_tenant_scoped():
    service = _service_module()
    engine, db = _db()
    storage = FakeStorage()
    try:
        first_mailbox = FakeMailboxClient(_message(), {"attachment-1": b"tenant-one"})
        second_mailbox = FakeMailboxClient(_message(), {"attachment-1": b"tenant-two"})
        first = service.ingest_gmail_message(
            db,
            owner_sub="owner-1",
            message_id="gmail-1",
            mailbox_client=first_mailbox,
            storage=storage,
            provider="INDEED",
            allowed_senders=(),
        )
        second = service.ingest_gmail_message(
            db,
            owner_sub="owner-2",
            message_id="gmail-1",
            mailbox_client=second_mailbox,
            storage=storage,
            provider="INDEED",
            allowed_senders=(),
        )

        assert first.event.id != second.event.id
    finally:
        db.close()
        engine.dispose()


def test_existing_indeed_event_without_task_is_backfilled_idempotently():
    service = _service_module()
    from app.domains.candidate_ingestion import repository
    from app.domains.candidate_ingestion.models import IndeedEmailResumeTask

    engine, db = _db()
    mailbox = FakeMailboxClient(_indeed_link_message(), {})
    try:
        _seed_synced_job(db)
        event = repository.create_event(
            db,
            owner_sub="owner-1",
            source="EMAIL",
            provider="INDEED",
            source_account="katherine@example.com",
            external_id="gmail-indeed-link",
            status="NEEDS_REVIEW",
            raw_metadata={
                "gmail_message_id": "gmail-indeed-link",
                "source_account": "katherine@example.com",
            },
        )
        event.last_error_code = "RESUME_ATTACHMENT_MISSING"
        event.last_error_message = "legacy event"
        db.commit()
        event_id = event.id

        first = service.ingest_gmail_message(
            db,
            owner_sub="owner-1",
            message_id="gmail-indeed-link",
            mailbox_client=mailbox,
            provider="INDEED",
            source_account="katherine@example.com",
        )

        assert first.created is False
        assert first.event.id == event_id
        assert first.event.status == "RECEIVED"
        assert first.event.last_error_code == "RESUME_DOWNLOAD_PENDING"
        assert first.event.raw_metadata["candidate_name"] == "Ana Perez"
        assert first.event.raw_metadata["job_title"] == "Country Manager Chile"
        assert db.query(IndeedEmailResumeTask).count() == 1
        task = db.query(IndeedEmailResumeTask).one()
        assert task.status == "WAITING_DOWNLOAD"
        assert task.ingestion_event_id == event_id
        assert mailbox.message_calls == 1

        second = service.ingest_gmail_message(
            db,
            owner_sub="owner-1",
            message_id="gmail-indeed-link",
            mailbox_client=mailbox,
            provider="INDEED",
            source_account="katherine@example.com",
        )

        assert second.created is False
        assert second.event.id == event_id
        assert db.query(IndeedEmailResumeTask).count() == 1
        assert mailbox.message_calls == 1
    finally:
        db.close()
        engine.dispose()


def test_sender_domain_filter_blocks_unrelated_incremental_mail_before_persisting():
    service = _service_module()
    from app.domains.candidate_ingestion.models import CandidateIngestionEvent
    from app.integrations.email_ingestion.parser import EmailSenderNotAllowed

    engine, db = _db()
    message = _message()
    message["payload"]["headers"][0] = {
        "name": "From",
        "value": "Personal <person@example.com>",
    }
    mailbox = FakeMailboxClient(message, {"attachment-1": b"pdfdata"})
    try:
        with pytest.raises(EmailSenderNotAllowed):
            service.ingest_gmail_message(
                db,
                owner_sub="owner-1",
                message_id="gmail-1",
                mailbox_client=mailbox,
                provider="INDEED",
                allowed_sender_domains=("indeedemail.com",),
            )

        assert db.query(CandidateIngestionEvent).count() == 0
        assert mailbox.attachment_calls == []
    finally:
        db.close()
        engine.dispose()


def test_sender_domain_filter_allows_subdomains_of_configured_domain():
    service = _service_module()
    engine, db = _db()
    message = _indeed_link_message()
    message["payload"]["headers"][0] = {
        "name": "From",
        "value": "Indeed <conversation@notify.indeedemail.com>",
    }
    mailbox = FakeMailboxClient(message, {})
    try:
        _seed_synced_job(db)
        result = service.ingest_gmail_message(
            db,
            owner_sub="owner-1",
            message_id="gmail-indeed-link",
            mailbox_client=mailbox,
            provider="INDEED",
            source_account="katherine@example.com",
            allowed_sender_domains=("indeedemail.com",),
        )

        assert result.event.indeed_email_resume_task is not None
        assert result.event.indeed_email_resume_task.status == "WAITING_DOWNLOAD"
    finally:
        db.close()
        engine.dispose()