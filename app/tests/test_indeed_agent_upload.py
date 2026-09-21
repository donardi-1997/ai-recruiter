"""Contracts for ephemeral Indeed resume URLs and idempotent PDF upload."""

from __future__ import annotations

import base64
import hashlib
import io
import zipfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.domains.candidate_ingestion.models import (
    CandidateIngestionDocument,
    CandidateIngestionEvent,
    IndeedEmailResumeTask,
)


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
        return f"candidate-ingestion/{event_id}/{attachment_id}/{filename}"


class FakeMailbox:
    def __init__(self, message):
        self.message = message
        self.calls = []

    def get_message(self, message_id):
        self.calls.append(message_id)
        assert message_id == self.message["id"]
        return self.message


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def _message(resume_url="https://secure.indeed.com/resume/temporary"):
    html = (
        '<html><body><p>Wendy Dayanna Marquez Rincon se postuló para '
        'Analista de Automatizacion e IA</p>'
        f'<a href="{resume_url}">Ver CV</a></body></html>'
    )
    encoded = base64.urlsafe_b64encode(html.encode("utf-8")).decode("ascii").rstrip("=")
    return {
        "id": "gmail-indeed-1",
        "threadId": "thread-1",
        "internalDate": "1789680000000",
        "payload": {
            "headers": [
                {
                    "name": "From",
                    "value": "Indeed <conversation-notify@indeedemail.com>",
                },
                {"name": "Subject", "value": "Nueva postulacion"},
            ],
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": encoded},
                }
            ],
        },
    }


DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _docx_bytes(text="Wendy Dayanna Marquez Rincon"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
        )
        archive.writestr(
            "word/document.xml",
            f'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>',
        )
    return buffer.getvalue()


def _event_task(db: Session, *, owner_sub="owner-1"):
    event = CandidateIngestionEvent(
        owner_sub=owner_sub,
        source="EMAIL",
        provider="INDEED",
        source_account="talent@example.com",
        external_id="gmail-indeed-1",
        status="RECEIVED",
        raw_metadata={
            "gmail_message_id": "gmail-indeed-1",
            "candidate_name": "Wendy Dayanna Marquez Rincon",
            "job_title": "Analista de Automatizacion e IA",
        },
        last_error_code="RESUME_DOWNLOAD_PENDING",
        last_error_message="El CV de Indeed esta pendiente de descarga.",
    )
    db.add(event)
    db.flush()
    task = IndeedEmailResumeTask(
        owner_sub=owner_sub,
        ingestion_event_id=event.id,
        candidate_name="Wendy Dayanna Marquez Rincon",
        job_title="Analista de Automatizacion e IA",
        status="WAITING_DOWNLOAD",
    )
    db.add(task)
    db.commit()
    db.refresh(event)
    db.refresh(task)
    return event, task


def test_claim_refetches_gmail_and_returns_resume_url_without_persisting_it():
    from app.domains.candidate_ingestion import indeed_email_agent_service as service

    engine, db = _db()
    event, task = _event_task(db)
    mailbox = FakeMailbox(_message())
    try:
        claimed = service.claim_next_task_with_resume_url(
            db,
            owner_sub="owner-1",
            mailbox_client=mailbox,
        )

        assert claimed is not None
        assert claimed.task_id == task.id
        assert claimed.resume_url == "https://secure.indeed.com/resume/temporary"
        assert mailbox.calls == ["gmail-indeed-1"]

        db.refresh(event)
        db.refresh(task)
        assert "resume_url" not in (event.raw_metadata or {})
        assert claimed.resume_url not in str(event.raw_metadata)
        assert claimed.resume_url not in str(event.last_error_message or "")
        assert claimed.resume_url not in str(task.last_error_message or "")
    finally:
        db.close()
        engine.dispose()


def test_valid_pdf_upload_completes_task_and_keeps_event_undispatched():
    from app.domains.candidate_ingestion import indeed_email_agent_service as service

    engine, db = _db()
    event, task = _event_task(db)
    storage = FakeStorage()
    try:
        claimed = service.claim_next_task(db, owner_sub="owner-1")
        data = b"%PDF-1.7\nvalid-pdf"
        document = service.store_resume_pdf(
            db,
            owner_sub="owner-1",
            task_id=task.id,
            lease_token=claimed.lease_token,
            filename="wendy.pdf",
            content_type="application/pdf",
            data=data,
            storage=storage,
        )

        assert document.document_sha256 == hashlib.sha256(data).hexdigest()
        assert db.query(CandidateIngestionDocument).count() == 1
        assert len(storage.calls) == 1
        db.refresh(event)
        db.refresh(task)
        assert event.status == "STORED"
        assert event.last_error_code is None
        assert event.last_error_message is None
        assert event.queue_dispatched_at is None
        assert task.status == "COMPLETED"
        assert task.lease_token is None
        assert task.lease_expires_at is None
    finally:
        db.close()
        engine.dispose()


def test_valid_docx_upload_completes_task_and_preserves_original_format():
    from app.domains.candidate_ingestion import indeed_email_agent_service as service

    engine, db = _db()
    event, task = _event_task(db)
    storage = FakeStorage()
    try:
        claimed = service.claim_next_task(db, owner_sub="owner-1")
        data = _docx_bytes()
        document = service.store_resume_document(
            db,
            owner_sub="owner-1",
            task_id=task.id,
            lease_token=claimed.lease_token,
            filename="CVAlejandracamachosaenz.docx",
            content_type=DOCX_CONTENT_TYPE,
            data=data,
            storage=storage,
        )

        assert document.filename == "CVAlejandracamachosaenz.docx"
        assert document.content_type == DOCX_CONTENT_TYPE
        assert document.document_sha256 == hashlib.sha256(data).hexdigest()
        assert storage.calls == [
            {
                "event_id": event.id,
                "attachment_id": f"indeed-agent-{task.id}",
                "filename": "CVAlejandracamachosaenz.docx",
                "data": data,
                "content_type": DOCX_CONTENT_TYPE,
            }
        ]
        db.refresh(task)
        assert task.status == "COMPLETED"
    finally:
        db.close()
        engine.dispose()


def test_uploaded_pdf_is_dispatched_once_by_existing_candidate_ingestion_repair(monkeypatch):
    from app.domains.candidate_ingestion import indeed_email_agent_service as service
    from app.workers import candidate_ingestions

    engine, db = _db()
    event, task = _event_task(db)
    storage = FakeStorage()
    sent = []
    monkeypatch.setattr(
        candidate_ingestions.queue,
        "send_candidate_ingestion",
        lambda event_id: sent.append(event_id),
    )
    try:
        claimed = service.claim_next_task(db, owner_sub="owner-1")
        service.store_resume_pdf(
            db,
            owner_sub="owner-1",
            task_id=task.id,
            lease_token=claimed.lease_token,
            filename="candidate.pdf",
            content_type="application/pdf",
            data=b"%PDF-1.7\nqueued",
            storage=storage,
        )

        assert candidate_ingestions.dispatch_undispatched_ingestions(db) == 1
        assert sent == [event.id]
        assert candidate_ingestions.dispatch_undispatched_ingestions(db) == 0
        assert sent == [event.id]
    finally:
        db.close()
        engine.dispose()


def test_repeated_same_upload_after_completion_is_idempotent_even_with_old_lease():
    from app.domains.candidate_ingestion import indeed_email_agent_service as service

    engine, db = _db()
    _, task = _event_task(db)
    storage = FakeStorage()
    try:
        claimed = service.claim_next_task(db, owner_sub="owner-1")
        data = b"%PDF-1.7\nsame-pdf"
        first = service.store_resume_pdf(
            db,
            owner_sub="owner-1",
            task_id=task.id,
            lease_token=claimed.lease_token,
            filename="candidate.pdf",
            content_type="application/pdf",
            data=data,
            storage=storage,
        )
        second = service.store_resume_pdf(
            db,
            owner_sub="owner-1",
            task_id=task.id,
            lease_token=claimed.lease_token,
            filename="candidate.pdf",
            content_type="application/pdf",
            data=data,
            storage=storage,
        )

        assert second.id == first.id
        assert db.query(CandidateIngestionDocument).count() == 1
        assert len(storage.calls) == 1
    finally:
        db.close()
        engine.dispose()


def test_existing_different_document_is_conflict_not_replaced():
    from app.domains.candidate_ingestion import indeed_email_agent_service as service

    engine, db = _db()
    _, task = _event_task(db)
    storage = FakeStorage()
    try:
        claimed = service.claim_next_task(db, owner_sub="owner-1")
        service.store_resume_pdf(
            db,
            owner_sub="owner-1",
            task_id=task.id,
            lease_token=claimed.lease_token,
            filename="candidate.pdf",
            content_type="application/pdf",
            data=b"%PDF-1.7\nfirst",
            storage=storage,
        )

        with pytest.raises(service.ResumeUploadConflict):
            service.store_resume_pdf(
                db,
                owner_sub="owner-1",
                task_id=task.id,
                lease_token=claimed.lease_token,
                filename="candidate.pdf",
                content_type="application/pdf",
                data=b"%PDF-1.7\ndifferent",
                storage=storage,
            )

        assert db.query(CandidateIngestionDocument).count() == 1
        assert len(storage.calls) == 1
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("content_type", "data", "expected_status"),
    [
        pytest.param("text/plain", b"%PDF-1.7\nvalid", 422, id="invalid-content-type"),
        pytest.param("application/pdf", b"not-a-pdf", 422, id="invalid-pdf-signature"),
        pytest.param(
            DOCX_CONTENT_TYPE,
            b"PK-not-a-real-docx",
            422,
            id="invalid-docx-signature",
        ),
        pytest.param(
            "application/pdf",
            b"%PDF-" + b"x" * (15 * 1024 * 1024 + 1),
            413,
            id="pdf-too-large",
        ),
    ],
)
def test_upload_validation_rejects_invalid_content_before_storage(
    content_type,
    data,
    expected_status,
):
    from app.domains.candidate_ingestion import indeed_email_agent_service as service

    engine, db = _db()
    _, task = _event_task(db)
    storage = FakeStorage()
    try:
        claimed = service.claim_next_task(db, owner_sub="owner-1")
        with pytest.raises(service.ResumeUploadValidationError) as caught:
            service.store_resume_pdf(
                db,
                owner_sub="owner-1",
                task_id=task.id,
                lease_token=claimed.lease_token,
                filename="candidate.pdf",
                content_type=content_type,
                data=data,
                storage=storage,
            )

        assert caught.value.status_code == expected_status
        assert storage.calls == []
        assert db.query(CandidateIngestionDocument).count() == 0
    finally:
        db.close()
        engine.dispose()
