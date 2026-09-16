"""Contracts for durable Gmail -> Candidate Ingestion Core handoff."""

import importlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401 - register shared tables in Base metadata
from app.db import Base


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


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


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
