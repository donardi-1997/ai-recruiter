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
from app.infrastructure.imports.queue import ReceivedImportMessage
from app.models import ImportBatch, Job
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
