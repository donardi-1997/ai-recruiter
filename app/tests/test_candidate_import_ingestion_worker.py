"""Contracts for the resumable Bedrock ingestion stage of candidate imports."""

import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.infrastructure.imports import ingestion
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


def _seed_prepared_batch(
    db,
    *,
    changed_in_batch: bool,
    current_stage: str = "DEDUPLICATING",
    ingestion_job_id: str | None = None,
) -> ImportBatch:
    started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    job = Job(id=_uuid(), title="Backend Developer", owner_sub="owner-a")
    candidate = Candidate(
        id=_uuid(),
        name="Ana Gomez",
        email="ana@example.com",
        owner_sub="owner-a",
    )
    db.add_all([job, candidate])
    db.flush()

    batch = ImportBatch(
        id=_uuid(),
        job_id=job.id,
        owner_sub="owner-a",
        status="PROCESSING",
        current_stage=current_stage,
        upload_total=1,
        uploaded_items=1,
        total_items=1,
        processed_items=1,
        successful_items=1,
        started_at=started_at,
        bedrock_ingestion_job_id=ingestion_job_id,
    )
    db.add(batch)
    db.flush()

    document_hash = "a" * 64
    item = ImportItem(
        id=_uuid(),
        batch_id=batch.id,
        kind="DOCUMENT",
        original_filename="ana.pdf",
        staging_s3_key="imports/batch/ana.pdf",
        content_type="application/pdf",
        size_bytes=100,
        document_sha256=document_hash,
        candidate_id=candidate.id,
        status="COMPLETED",
        current_stage="DEDUPLICATING",
        outcome="CREATED",
        completed_at=started_at + timedelta(minutes=1),
    )
    identity = CandidateIdentity(
        owner_sub="owner-a",
        candidate_id=candidate.id,
        kind="DOCUMENT_SHA256",
        value=document_hash,
        created_at=(
            started_at + timedelta(seconds=1)
            if changed_in_batch
            else started_at - timedelta(days=1)
        ),
    )
    db.add_all([item, identity])
    db.commit()
    db.refresh(batch)
    return batch


def test_changed_batch_starts_one_ingestion_and_advances_after_complete(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch = _seed_prepared_batch(db, changed_in_batch=True)
        batch_id = batch.id

    starts = []
    status_reads = []
    monkeypatch.setattr(
        ingestion,
        "start_batch_ingestion",
        lambda batch_id: starts.append(batch_id) or ("ing-123", "STARTING"),
    )
    monkeypatch.setattr(
        ingestion,
        "get_ingestion_status",
        lambda job_id: status_reads.append(job_id) or "COMPLETE",
    )

    with db_factory() as db:
        worker._run_ingestion_stage(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.bedrock_ingestion_job_id == "ing-123"
        assert batch.status == "PROCESSING"
        assert batch.current_stage == "EVALUATING"

    assert starts == [batch_id]
    assert status_reads == ["ing-123"]


def test_ingestion_resume_polls_existing_job_without_starting_another(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch = _seed_prepared_batch(
            db,
            changed_in_batch=True,
            current_stage="INGESTING",
            ingestion_job_id="ing-existing",
        )
        batch_id = batch.id

    monkeypatch.setattr(
        ingestion,
        "start_batch_ingestion",
        lambda batch_id: (_ for _ in ()).throw(
            AssertionError("resume must not start a second ingestion")
        ),
    )
    reads = []
    monkeypatch.setattr(
        ingestion,
        "get_ingestion_status",
        lambda job_id: reads.append(job_id) or "COMPLETE",
    )

    with db_factory() as db:
        worker._run_ingestion_stage(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.bedrock_ingestion_job_id == "ing-existing"
        assert batch.current_stage == "EVALUATING"

    assert reads == ["ing-existing"]


def test_unchanged_batch_skips_bedrock_and_advances_to_evaluating(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch = _seed_prepared_batch(db, changed_in_batch=False)
        batch_id = batch.id

    monkeypatch.setattr(
        ingestion,
        "start_batch_ingestion",
        lambda batch_id: (_ for _ in ()).throw(
            AssertionError("unchanged documents must skip ingestion")
        ),
    )
    monkeypatch.setattr(
        ingestion,
        "get_ingestion_status",
        lambda job_id: (_ for _ in ()).throw(
            AssertionError("unchanged documents have no ingestion to poll")
        ),
    )

    with db_factory() as db:
        worker._run_ingestion_stage(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.bedrock_ingestion_job_id is None
        assert batch.status == "PROCESSING"
        assert batch.current_stage == "EVALUATING"


def test_failed_ingestion_marks_batch_failed_with_public_safe_error(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch = _seed_prepared_batch(db, changed_in_batch=True)
        batch_id = batch.id

    monkeypatch.setattr(
        ingestion,
        "start_batch_ingestion",
        lambda batch_id: ("ing-failed", "STARTING"),
    )
    monkeypatch.setattr(ingestion, "get_ingestion_status", lambda job_id: "FAILED")

    with db_factory() as db:
        worker._run_ingestion_stage(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.status == "FAILED"
        assert batch.current_stage == "INGESTING"
        assert batch.last_error_code == "BEDROCK_INGESTION_FAILED"
        assert batch.last_error_message
        assert "arn:aws" not in batch.last_error_message
        assert "AccessDenied" not in batch.last_error_message
        assert batch.completed_at is not None


def test_ingestion_timeout_marks_batch_failed_without_synthetic_progress(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch = _seed_prepared_batch(db, changed_in_batch=True)
        batch_id = batch.id

    monkeypatch.setattr(
        ingestion,
        "start_batch_ingestion",
        lambda batch_id: ("ing-running", "STARTING"),
    )
    monkeypatch.setattr(ingestion, "get_ingestion_status", lambda job_id: "IN_PROGRESS")

    with db_factory() as db:
        worker._run_ingestion_stage(
            db,
            db.get(ImportBatch, batch_id),
            timeout_seconds=0,
        )

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.status == "FAILED"
        assert batch.current_stage == "INGESTING"
        assert batch.last_error_code == "BEDROCK_INGESTION_TIMEOUT"
        assert batch.completed_at is not None
