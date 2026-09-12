"""Contracts for ranking terminalization and full import-worker orchestration."""

import os
import tempfile
import uuid
from datetime import datetime, timezone

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.domains.ranking import service as ranking_service
from app.domains.ranking.exceptions import RankingAlreadyRunning, RankingJobNotFound
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


def _seed_batch(
    db,
    *,
    stage: str = "RANKING",
    status: str = "PROCESSING",
    successful_items: int = 2,
    failed_items: int = 0,
    evaluation_failed_items: int = 0,
) -> ImportBatch:
    job = Job(
        id=_uuid(),
        title="Backend Developer",
        description="Python APIs",
        owner_sub="owner-a",
    )
    db.add(job)
    db.flush()
    batch = ImportBatch(
        id=_uuid(),
        job_id=job.id,
        owner_sub="owner-a",
        status=status,
        current_stage=stage,
        upload_total=max(1, successful_items + failed_items),
        uploaded_items=max(1, successful_items + failed_items),
        total_items=successful_items + failed_items,
        processed_items=successful_items + failed_items,
        successful_items=successful_items,
        failed_items=failed_items,
        evaluated_items=successful_items,
        evaluation_failed_items=evaluation_failed_items,
        started_at=datetime.now(timezone.utc),
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


def test_ranking_success_completes_batch_and_persists_version(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch = _seed_batch(db)
        batch_id = batch.id

    calls = []
    monkeypatch.setattr(
        ranking_service,
        "materialize_ranking_from_evaluations",
        lambda db, *, job_id, owner_sub, scope: calls.append(
            (job_id, owner_sub, scope)
        )
        or {"ranking_version": 7},
    )

    with db_factory() as db:
        worker._run_ranking_stage(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.status == "COMPLETED"
        assert batch.current_stage == "COMPLETED"
        assert batch.ranking_ready is True
        assert batch.ranking_version == 7
        assert batch.completed_at is not None

    assert len(calls) == 1
    assert calls[0][1:] == ("owner-a", "assigned")


def test_ranking_success_with_item_or_evaluation_failures_completes_with_errors(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch = _seed_batch(
            db,
            successful_items=2,
            failed_items=1,
            evaluation_failed_items=1,
        )
        batch_id = batch.id

    monkeypatch.setattr(
        ranking_service,
        "materialize_ranking_from_evaluations",
        lambda *args, **kwargs: {"ranking_version": 3},
    )

    with db_factory() as db:
        worker._run_ranking_stage(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.status == "COMPLETED_WITH_ERRORS"
        assert batch.current_stage == "COMPLETED"
        assert batch.ranking_ready is True
        assert batch.ranking_version == 3


def test_ranking_lock_retries_with_bounded_backoff_then_succeeds(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch = _seed_batch(db)
        batch_id = batch.id

    attempts = 0
    sleeps = []

    def _materialize(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RankingAlreadyRunning()
        return {"ranking_version": 5}

    monkeypatch.setattr(
        ranking_service,
        "materialize_ranking_from_evaluations",
        _materialize,
    )
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: sleeps.append(seconds))

    with db_factory() as db:
        worker._run_ranking_stage(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.status == "COMPLETED"
        assert batch.ranking_version == 5

    assert attempts == 3
    assert sleeps == [1, 2]


def test_ranking_lock_exhaustion_marks_terminal_failed(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch = _seed_batch(db)
        batch_id = batch.id

    attempts = 0
    sleeps = []

    def _locked(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise RankingAlreadyRunning()

    monkeypatch.setattr(
        ranking_service,
        "materialize_ranking_from_evaluations",
        _locked,
    )
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: sleeps.append(seconds))

    with db_factory() as db:
        worker._run_ranking_stage(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.status == "FAILED"
        assert batch.current_stage == "RANKING"
        assert batch.ranking_ready is False
        assert batch.last_error_code == "RANKING_LOCK_TIMEOUT"
        assert batch.last_error_message
        assert batch.completed_at is not None

    assert attempts == 4
    assert sleeps == [1, 2, 4]


def test_missing_job_during_ranking_marks_terminal_failed(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch = _seed_batch(db)
        batch_id = batch.id

    monkeypatch.setattr(
        ranking_service,
        "materialize_ranking_from_evaluations",
        lambda *args, **kwargs: (_ for _ in ()).throw(RankingJobNotFound()),
    )

    with db_factory() as db:
        worker._run_ranking_stage(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.status == "FAILED"
        assert batch.current_stage == "RANKING"
        assert batch.last_error_code == "JOB_NOT_FOUND"
        assert batch.last_error_message == "La vacante ya no esta disponible."
        assert batch.completed_at is not None


def test_unexpected_ranking_persistence_failure_remains_retryable(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch = _seed_batch(db)
        batch_id = batch.id

    monkeypatch.setattr(
        ranking_service,
        "materialize_ranking_from_evaluations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("database connection reset")
        ),
    )

    with db_factory() as db:
        with pytest.raises(RuntimeError, match="database connection reset"):
            worker._run_ranking_stage(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.status == "PROCESSING"
        assert batch.current_stage == "RANKING"
        assert batch.ranking_ready is False
        assert batch.completed_at is None


def test_process_batch_runs_remaining_stages_then_cleans_staging(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch = _seed_batch(
            db,
            stage="UPLOADING",
            status="QUEUED",
            successful_items=0,
        )
        batch.total_items = 1
        batch.processed_items = 0
        batch.evaluated_items = 0
        db.commit()
        batch_id = batch.id

    events = []

    class _Keeper:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            events.append("lease-start")

        def stop(self):
            events.append("lease-stop")

    def _prepare(db, batch):
        events.append("prepare")
        batch.status = "PROCESSING"
        batch.current_stage = "DEDUPLICATING"
        batch.successful_items = 1
        batch.processed_items = 1
        db.commit()

    def _ingest(db, batch):
        events.append("ingest")
        batch.current_stage = "EVALUATING"
        db.commit()

    def _evaluate(db, batch):
        events.append("evaluate")
        batch.evaluated_items = 1
        batch.current_stage = "RANKING"
        db.commit()

    def _rank(db, batch):
        events.append("rank")
        batch.status = "COMPLETED"
        batch.current_stage = "COMPLETED"
        batch.ranking_ready = True
        batch.ranking_version = 4
        batch.completed_at = datetime.now(timezone.utc)
        batch.processing_token = None
        batch.heartbeat_at = None
        db.commit()

    monkeypatch.setattr(worker, "SessionLocal", db_factory)
    monkeypatch.setattr(worker, "LeaseKeeper", _Keeper)
    monkeypatch.setattr(worker, "_prepare_batch_documents", _prepare)
    monkeypatch.setattr(worker, "_run_ingestion_stage", _ingest)
    monkeypatch.setattr(worker, "_run_evaluation_stage", _evaluate)
    monkeypatch.setattr(worker, "_run_ranking_stage", _rank, raising=False)
    monkeypatch.setattr(
        worker.storage,
        "delete_staging_prefix",
        lambda value: events.append(f"cleanup:{value}"),
    )

    worker.process_batch(batch_id, receipt_handle="rh-1")

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.status == "COMPLETED"
        assert batch.ranking_ready is True
        assert batch.ranking_version == 4

    assert events == [
        "lease-start",
        "prepare",
        "ingest",
        "evaluate",
        "rank",
        f"cleanup:{batch_id}",
        "lease-stop",
    ]


def test_process_batch_with_no_usable_candidates_fails_before_ingestion(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch = _seed_batch(
            db,
            stage="UPLOADING",
            status="QUEUED",
            successful_items=0,
        )
        batch.total_items = 1
        batch.processed_items = 0
        db.commit()
        batch_id = batch.id

    later_stages = []

    class _Keeper:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            pass

    def _prepare(db, batch):
        batch.status = "PROCESSING"
        batch.current_stage = "DEDUPLICATING"
        batch.successful_items = 0
        batch.failed_items = 1
        batch.processed_items = 1
        db.commit()

    monkeypatch.setattr(worker, "SessionLocal", db_factory)
    monkeypatch.setattr(worker, "LeaseKeeper", _Keeper)
    monkeypatch.setattr(worker, "_prepare_batch_documents", _prepare)
    monkeypatch.setattr(
        worker,
        "_run_ingestion_stage",
        lambda *args, **kwargs: later_stages.append("ingest"),
    )
    monkeypatch.setattr(
        worker,
        "_run_evaluation_stage",
        lambda *args, **kwargs: later_stages.append("evaluate"),
    )
    monkeypatch.setattr(
        worker,
        "_run_ranking_stage",
        lambda *args, **kwargs: later_stages.append("rank"),
        raising=False,
    )
    cleaned = []
    monkeypatch.setattr(
        worker.storage,
        "delete_staging_prefix",
        lambda value: cleaned.append(value),
    )

    worker.process_batch(batch_id, receipt_handle="rh-empty")

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.status == "FAILED"
        assert batch.current_stage == "DEDUPLICATING"
        assert batch.last_error_code == "NO_USABLE_CANDIDATES"
        assert batch.completed_at is not None

    assert later_stages == []
    assert cleaned == [batch_id]


def test_terminal_cleanup_failure_does_not_reopen_completed_batch(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch = _seed_batch(db, status="COMPLETED", stage="COMPLETED")
        batch.ranking_ready = True
        batch.ranking_version = 1
        batch.completed_at = datetime.now(timezone.utc)
        db.commit()
        batch_id = batch.id

    monkeypatch.setattr(worker, "SessionLocal", db_factory)
    monkeypatch.setattr(
        worker.storage,
        "delete_staging_prefix",
        lambda value: (_ for _ in ()).throw(RuntimeError("temporary S3 outage")),
    )

    worker.process_batch(batch_id, receipt_handle="rh-terminal")

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.status == "COMPLETED"
        assert batch.ranking_ready is True
