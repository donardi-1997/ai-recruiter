"""Contracts for the durable SQS candidate-import worker."""

import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.domains.candidate_imports import repository
from app.infrastructure.imports import documents, storage
from app.infrastructure.imports.documents import ExpandedDocument, ParsedDocument
from app.infrastructure.imports.queue import ReceivedImportMessage
from app.models import Candidate, CandidateIdentity, ImportBatch, ImportItem, Job
from app.workers import candidate_imports as worker


def _uuid() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def db_factory():
    fd, path = tempfile.mkstemp(suffix=".db")
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
        os.close(fd)
        os.unlink(path)


@pytest.fixture()
def queued_batch_id(db_factory):
    with db_factory() as db:
        job = Job(id=_uuid(), title="Backend Developer", owner_sub="owner-a")
        db.add(job)
        db.flush()
        batch = ImportBatch(
            id=_uuid(),
            job_id=job.id,
            owner_sub="owner-a",
            status="QUEUED",
            current_stage="UPLOADING",
            upload_total=1,
            uploaded_items=1,
            total_items=1,
        )
        db.add(batch)
        db.commit()
        return batch.id


def _processing_batch(db, *, total_items: int) -> ImportBatch:
    job = Job(id=_uuid(), title="Backend Developer", owner_sub="owner-a")
    db.add(job)
    db.flush()
    batch = ImportBatch(
        id=_uuid(),
        job_id=job.id,
        owner_sub="owner-a",
        status="PROCESSING",
        current_stage="VALIDATING",
        upload_total=1,
        uploaded_items=1,
        total_items=total_items,
        started_at=datetime.now(timezone.utc),
    )
    db.add(batch)
    db.flush()
    return batch


def _uploaded_item(
    db,
    *,
    batch_id: str,
    filename: str,
    kind: str = "DOCUMENT",
    content_type: str = "application/pdf",
    parent_item_id: str | None = None,
) -> ImportItem:
    item = ImportItem(
        id=_uuid(),
        batch_id=batch_id,
        parent_item_id=parent_item_id,
        kind=kind,
        original_filename=filename,
        staging_s3_key=f"staging/{filename}",
        content_type=content_type,
        size_bytes=100,
        status="UPLOADED",
        current_stage="UPLOADING",
    )
    db.add(item)
    db.flush()
    return item


def _parsed(
    filename: str,
    *,
    sha256: str,
    email: str | None = None,
    phone: str | None = None,
) -> ParsedDocument:
    return ParsedDocument(
        filename=filename,
        content_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if filename.endswith(".docx")
            else "application/pdf"
        ),
        display_name=filename.rsplit(".", 1)[0].replace("_", " ").title(),
        email=email,
        phone=phone,
        text="Candidate CV",
        header_text="Candidate CV",
        sha256=sha256,
    )


def test_duplicate_delivery_cannot_claim_fresh_lease(db_factory, queued_batch_id):
    now = datetime.now(timezone.utc)
    with db_factory() as db:
        assert repository.claim_batch(
            db,
            batch_id=queued_batch_id,
            token="worker-a",
            now=now,
            lease_seconds=300,
        )
        assert not repository.claim_batch(
            db,
            batch_id=queued_batch_id,
            token="worker-b",
            now=now + timedelta(seconds=30),
            lease_seconds=300,
        )
        assert repository.claim_batch(
            db,
            batch_id=queued_batch_id,
            token="worker-b",
            now=now + timedelta(seconds=301),
            lease_seconds=300,
        )


def test_worker_repairs_queued_batch_without_dispatch_timestamp(
    db_factory,
    queued_batch_id,
    monkeypatch,
):
    sent = []
    monkeypatch.setattr(
        worker.queue,
        "send_import_batch",
        lambda batch_id: sent.append(batch_id),
    )

    with db_factory() as db:
        batch = db.get(ImportBatch, queued_batch_id)
        batch.queue_dispatched_at = None
        db.commit()

        assert worker.dispatch_undispatched_batches(db) == 1
        db.refresh(batch)
        assert batch.queue_dispatched_at is not None

    assert sent == [queued_batch_id]


def test_lease_keeper_refreshes_owned_lease_and_sqs_visibility(
    db_factory,
    queued_batch_id,
    monkeypatch,
):
    initial = datetime.now(timezone.utc) - timedelta(seconds=120)
    with db_factory() as db:
        assert repository.claim_batch(
            db,
            batch_id=queued_batch_id,
            token="worker-a",
            now=initial,
            lease_seconds=300,
        )

    visibility = []
    monkeypatch.setattr(worker, "SessionLocal", db_factory)
    monkeypatch.setattr(
        worker.queue,
        "extend_visibility",
        lambda receipt_handle, seconds: visibility.append((receipt_handle, seconds)),
    )

    keeper = worker.LeaseKeeper(
        batch_id=queued_batch_id,
        token="worker-a",
        receipt_handle="rh-active",
        interval_seconds=60,
        visibility_seconds=300,
    )
    keeper.beat_once()

    with db_factory() as db:
        batch = db.get(ImportBatch, queued_batch_id)
        assert batch.processing_token == "worker-a"
        assert batch.heartbeat_at is not None
        heartbeat = batch.heartbeat_at
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        assert heartbeat > initial

    assert visibility == [("rh-active", 300)]


def test_lease_keeper_wrong_token_does_not_take_over_batch(
    db_factory,
    queued_batch_id,
    monkeypatch,
):
    initial = datetime.now(timezone.utc) - timedelta(seconds=120)
    with db_factory() as db:
        assert repository.claim_batch(
            db,
            batch_id=queued_batch_id,
            token="worker-a",
            now=initial,
            lease_seconds=300,
        )

    monkeypatch.setattr(worker, "SessionLocal", db_factory)
    monkeypatch.setattr(worker.queue, "extend_visibility", lambda *args: None)

    keeper = worker.LeaseKeeper(
        batch_id=queued_batch_id,
        token="worker-b",
        receipt_handle="rh-duplicate",
        interval_seconds=60,
        visibility_seconds=300,
    )
    keeper.beat_once()

    with db_factory() as db:
        batch = db.get(ImportBatch, queued_batch_id)
        assert batch.processing_token == "worker-a"
        heartbeat = batch.heartbeat_at
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        assert heartbeat == initial


def test_zip_expansion_is_checkpointed_and_resume_skips_reexpansion(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch = _processing_batch(db, total_items=0)
        archive = _uploaded_item(
            db,
            batch_id=batch.id,
            filename="candidates.zip",
            kind="ARCHIVE",
            content_type="application/zip",
        )
        db.commit()
        batch_id = batch.id
        archive_id = archive.id
        archive_key = archive.staging_s3_key

    expand_calls = []
    child_writes = []
    canonical_writes = []

    def _read(key):
        if key == archive_key:
            return b"zip-payload"
        return b"candidate-payload"

    def _expand(data, *, remaining_documents, remaining_bytes):
        expand_calls.append((data, remaining_documents, remaining_bytes))
        return [
            ExpandedDocument(
                filename="ana.pdf",
                content_type="application/pdf",
                data=b"candidate-payload",
            )
        ]

    monkeypatch.setattr(storage, "read_staging_object", _read)
    monkeypatch.setattr(documents, "expand_zip", _expand)
    monkeypatch.setattr(
        storage,
        "write_staging_child",
        lambda **kwargs: child_writes.append(kwargs) or f"expanded/{kwargs['item_id']}/ana.pdf",
    )
    monkeypatch.setattr(
        documents,
        "extract_document",
        lambda data, filename: _parsed(
            filename,
            sha256="a" * 64,
            email="ana@example.com",
        ),
    )
    monkeypatch.setattr(
        storage,
        "write_canonical_candidate_document",
        lambda **kwargs: canonical_writes.append(kwargs)
        or storage.CanonicalWriteResult(key="documents/cv-ana.pdf", changed=True),
    )

    with db_factory() as db:
        worker._prepare_batch_documents(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        archive = db.get(ImportItem, archive_id)
        children = (
            db.query(ImportItem)
            .filter(ImportItem.parent_item_id == archive_id)
            .all()
        )
        assert archive.status == "COMPLETED"
        assert len(children) == 1
        assert children[0].status == "COMPLETED"
        assert batch.total_items == 1
        assert batch.processed_items == 1
        assert batch.successful_items == 1

        worker._prepare_batch_documents(db, batch)

    assert len(expand_calls) == 1
    assert len(child_writes) == 1
    assert len(canonical_writes) == 1


def test_same_candidate_only_updates_canonical_once_within_batch(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch = _processing_batch(db, total_items=2)
        first = _uploaded_item(db, batch_id=batch.id, filename="ana_old.pdf")
        second = _uploaded_item(db, batch_id=batch.id, filename="ana_new.pdf")
        db.commit()
        batch_id = batch.id
        first_id = first.id
        second_id = second.id

    parsed = {
        "ana_old.pdf": _parsed(
            "ana_old.pdf",
            sha256="a" * 64,
            email="ana@example.com",
        ),
        "ana_new.pdf": _parsed(
            "ana_new.pdf",
            sha256="b" * 64,
            email="ana@example.com",
        ),
    }
    canonical_writes = []

    monkeypatch.setattr(storage, "read_staging_object", lambda key: key.encode())
    monkeypatch.setattr(
        documents,
        "extract_document",
        lambda data, filename: parsed[filename],
    )
    monkeypatch.setattr(
        storage,
        "write_canonical_candidate_document",
        lambda **kwargs: canonical_writes.append(kwargs)
        or storage.CanonicalWriteResult(key="documents/cv-ana.pdf", changed=True),
    )

    with db_factory() as db:
        worker._prepare_batch_documents(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        first = db.get(ImportItem, first_id)
        second = db.get(ImportItem, second_id)
        assert first.status == "COMPLETED"
        assert second.status == "COMPLETED"
        assert first.candidate_id == second.candidate_id
        assert first.outcome == "CREATED"
        assert second.outcome == "REUSED"
        assert batch.processed_items == 2
        assert batch.successful_items == 2
        assert batch.reused_items == 1

    assert len(canonical_writes) == 1


def test_identity_conflict_fails_only_the_document(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch = _processing_batch(db, total_items=1)
        item = _uploaded_item(db, batch_id=batch.id, filename="conflict.pdf")
        first = Candidate(name="Email Owner", owner_sub="owner-a")
        second = Candidate(name="Phone Owner", owner_sub="owner-a")
        db.add_all([first, second])
        db.flush()
        db.add_all(
            [
                CandidateIdentity(
                    owner_sub="owner-a",
                    candidate_id=first.id,
                    kind="EMAIL",
                    value="ana@example.com",
                ),
                CandidateIdentity(
                    owner_sub="owner-a",
                    candidate_id=second.id,
                    kind="PHONE",
                    value="+573001234567",
                ),
            ]
        )
        db.commit()
        batch_id = batch.id
        item_id = item.id

    monkeypatch.setattr(storage, "read_staging_object", lambda key: b"candidate")
    monkeypatch.setattr(
        documents,
        "extract_document",
        lambda data, filename: _parsed(
            filename,
            sha256="c" * 64,
            email="ana@example.com",
            phone="+573001234567",
        ),
    )
    monkeypatch.setattr(
        storage,
        "write_canonical_candidate_document",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("conflict must not write canonical CV")),
    )

    with db_factory() as db:
        worker._prepare_batch_documents(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        item = db.get(ImportItem, item_id)
        assert item.status == "FAILED"
        assert item.error_code == "IDENTITY_CONFLICT"
        assert item.candidate_id is None
        assert batch.status == "PROCESSING"
        assert batch.processed_items == 1
        assert batch.successful_items == 0
        assert batch.failed_items == 1


def test_deleted_batch_message_is_acknowledged(monkeypatch):
    deleted = []

    def _missing(*args, **kwargs):
        raise worker.BatchMissing()

    monkeypatch.setattr(worker, "process_batch", _missing)
    monkeypatch.setattr(
        worker.queue,
        "delete_message",
        lambda handle: deleted.append(handle),
    )

    worker.handle_message(
        ReceivedImportMessage(
            batch_id="missing",
            receipt_handle="rh",
            receive_count=1,
        )
    )

    assert deleted == ["rh"]


def test_fifth_receive_marks_failed_safely_and_leaves_message_for_dlq(
    db_factory,
    queued_batch_id,
    monkeypatch,
):
    deleted = []

    def _boom(*args, **kwargs):
        raise RuntimeError(
            "AccessDeniedException for arn:aws:iam::123456789012:role/secret-runtime-role"
        )

    monkeypatch.setattr(worker, "SessionLocal", db_factory)
    monkeypatch.setattr(worker, "process_batch", _boom)
    monkeypatch.setattr(
        worker.queue,
        "delete_message",
        lambda handle: deleted.append(handle),
    )

    worker.handle_message(
        ReceivedImportMessage(
            batch_id=queued_batch_id,
            receipt_handle="rh-fifth",
            receive_count=5,
        )
    )

    with db_factory() as db:
        batch = db.get(ImportBatch, queued_batch_id)
        assert batch.status == "FAILED"
        assert batch.last_error_code == "IMPORT_RETRY_EXHAUSTED"
        assert batch.last_error_message
        assert "AccessDenied" not in batch.last_error_message
        assert "arn:aws" not in batch.last_error_message
        assert batch.completed_at is not None

    assert deleted == []
