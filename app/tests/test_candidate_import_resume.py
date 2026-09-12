"""Crash-recovery contracts for candidate-import document preparation."""

import os
import tempfile
import uuid
from datetime import datetime, timezone

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.infrastructure.imports import documents, storage
from app.infrastructure.imports.documents import ParsedDocument
from app.models import Candidate, ImportBatch, ImportItem, Job
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


def test_retry_after_canonical_write_failure_rewrites_same_candidate_once(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
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
            total_items=1,
            started_at=datetime.now(timezone.utc),
        )
        db.add(batch)
        db.flush()
        item = ImportItem(
            id=_uuid(),
            batch_id=batch.id,
            kind="DOCUMENT",
            original_filename="ana.pdf",
            staging_s3_key="imports/batch/ana.pdf",
            content_type="application/pdf",
            size_bytes=100,
            status="UPLOADED",
            current_stage="UPLOADING",
        )
        db.add(item)
        db.commit()
        batch_id = batch.id
        item_id = item.id

    parsed = ParsedDocument(
        filename="ana.pdf",
        content_type="application/pdf",
        display_name="Ana Gomez",
        email="ana@example.com",
        phone=None,
        text="Ana Gomez\nana@example.com",
        header_text="Ana Gomez\nana@example.com",
        sha256="a" * 64,
    )
    monkeypatch.setattr(storage, "read_staging_object", lambda key: b"candidate-payload")
    monkeypatch.setattr(documents, "extract_document", lambda data, filename: parsed)

    canonical_calls = []

    def _write_canonical(**kwargs):
        canonical_calls.append(kwargs)
        if len(canonical_calls) == 1:
            raise RuntimeError("temporary S3 write failure")
        return storage.CanonicalWriteResult(
            key="documents/cv-ana.pdf",
            changed=True,
        )

    monkeypatch.setattr(storage, "write_canonical_candidate_document", _write_canonical)

    with db_factory() as db:
        with pytest.raises(RuntimeError, match="temporary S3 write failure"):
            worker._prepare_batch_documents(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        assert db.query(Candidate).count() == 1
        item = db.get(ImportItem, item_id)
        assert item.status == "PROCESSING"

    with db_factory() as db:
        worker._prepare_batch_documents(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        item = db.get(ImportItem, item_id)
        assert db.query(Candidate).count() == 1
        assert item.status == "COMPLETED"
        assert item.candidate_id is not None
        assert batch.processed_items == 1
        assert batch.successful_items == 1

    assert len(canonical_calls) == 2
