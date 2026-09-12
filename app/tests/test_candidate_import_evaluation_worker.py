"""Contracts for bounded, resumable candidate-import evaluation."""

import os
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.domains.evaluations import repository as evaluations_repository
from app.domains.evaluations import service as evaluations_service
from app.models import Candidate, CandidateIdentity, Evaluation, ImportBatch, ImportItem, Job
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


def _complete_evaluation(
    db,
    *,
    candidate_id: str,
    job_id: str,
    created_at: datetime | None = None,
) -> Evaluation:
    evaluation = Evaluation(
        candidate_id=candidate_id,
        job_id=job_id,
        status="COMPLETED",
        match_score=85,
        recommendation="GOOD_MATCH",
        summary="Candidate evaluation summary with enough detail to satisfy the persisted evaluation contract. " * 2,
        strengths=["Python"],
        gaps=[],
        requirements=[],
        error_message=None,
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.add(evaluation)
    db.flush()
    return evaluation


def _failed_evaluation(db, *, candidate_id: str, job_id: str, internal: str) -> Evaluation:
    return evaluations_repository.create_evaluation(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
        match_score=0.0,
        recommendation="EVALUATION_FAILED",
        summary="No fue posible completar la evaluación. Intenta nuevamente.",
        strengths=[],
        gaps=[],
        requirements=[],
        status="FAILED",
        error_message=internal,
    )


def _seed_evaluation_batch(
    db,
    *,
    candidate_count: int = 1,
    identity_created_in_batch: bool = False,
    duplicate_first_candidate_item: bool = False,
):
    started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
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
        status="PROCESSING",
        current_stage="EVALUATING",
        upload_total=candidate_count,
        uploaded_items=candidate_count,
        total_items=candidate_count,
        processed_items=candidate_count,
        successful_items=candidate_count,
        started_at=started_at,
    )
    db.add(batch)
    db.flush()

    candidates = []
    for index in range(candidate_count):
        candidate = Candidate(
            id=_uuid(),
            name=f"Candidate {index}",
            email=f"candidate-{index}@example.com",
            owner_sub="owner-a",
        )
        db.add(candidate)
        db.flush()
        document_hash = f"{index + 1:064x}"
        db.add(
            CandidateIdentity(
                owner_sub="owner-a",
                candidate_id=candidate.id,
                kind="DOCUMENT_SHA256",
                value=document_hash,
                created_at=(
                    started_at + timedelta(seconds=1)
                    if identity_created_in_batch
                    else started_at - timedelta(days=1)
                ),
            )
        )
        db.add(
            ImportItem(
                id=_uuid(),
                batch_id=batch.id,
                kind="DOCUMENT",
                original_filename=f"candidate-{index}.pdf",
                staging_s3_key=f"imports/{batch.id}/candidate-{index}.pdf",
                content_type="application/pdf",
                size_bytes=100,
                document_sha256=document_hash,
                candidate_id=candidate.id,
                status="COMPLETED",
                current_stage="DEDUPLICATING",
                outcome="CREATED",
                completed_at=started_at + timedelta(minutes=1),
            )
        )
        candidates.append(candidate)

    if duplicate_first_candidate_item and candidates:
        first = candidates[0]
        first_hash = f"{1:064x}"
        db.add(
            ImportItem(
                id=_uuid(),
                batch_id=batch.id,
                kind="DOCUMENT",
                original_filename="candidate-0-duplicate.pdf",
                staging_s3_key=f"imports/{batch.id}/candidate-0-duplicate.pdf",
                content_type="application/pdf",
                size_bytes=100,
                document_sha256=first_hash,
                candidate_id=first.id,
                status="COMPLETED",
                current_stage="DEDUPLICATING",
                outcome="REUSED",
                completed_at=started_at + timedelta(minutes=1),
            )
        )
        batch.total_items += 1
        batch.processed_items += 1
        batch.successful_items += 1
        batch.reused_items += 1

    db.commit()
    db.refresh(batch)
    return batch, job, candidates


def _persist_complete_result(db, *, candidate_id: str, job_id: str):
    evaluation = evaluations_repository.create_evaluation(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
        match_score=88,
        recommendation="GOOD_MATCH",
        summary="Fresh candidate evaluation summary that is comfortably longer than the minimum contract length. " * 2,
        strengths=["Python"],
        gaps=[],
        requirements=[],
        status="COMPLETED",
        error_message=None,
    )
    return evaluation, True, None


def test_unchanged_candidate_reuses_complete_evaluation_without_llm(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch, job, candidates = _seed_evaluation_batch(
            db,
            identity_created_in_batch=False,
        )
        _complete_evaluation(
            db,
            candidate_id=candidates[0].id,
            job_id=job.id,
            created_at=batch.started_at - timedelta(days=1),
        )
        db.commit()
        batch_id = batch.id

    monkeypatch.setattr(worker, "SessionLocal", db_factory)
    monkeypatch.setattr(
        evaluations_service,
        "evaluate_candidate_for_owner",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unchanged complete evaluation must be reused")
        ),
    )

    with db_factory() as db:
        worker._run_evaluation_stage(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.evaluated_items == 1
        assert batch.evaluation_failed_items == 0
        assert batch.current_stage == "RANKING"


def test_changed_candidate_is_reevaluated_even_with_old_complete_evaluation(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch, job, candidates = _seed_evaluation_batch(
            db,
            identity_created_in_batch=True,
        )
        _complete_evaluation(
            db,
            candidate_id=candidates[0].id,
            job_id=job.id,
            created_at=batch.started_at - timedelta(days=1),
        )
        db.commit()
        batch_id = batch.id
        candidate_id = candidates[0].id
        job_id = job.id

    calls = []
    monkeypatch.setattr(worker, "SessionLocal", db_factory)

    def _evaluate(db, *, candidate_id, job_id, owner_sub):
        calls.append(candidate_id)
        return _persist_complete_result(db, candidate_id=candidate_id, job_id=job_id)

    monkeypatch.setattr(evaluations_service, "evaluate_candidate_for_owner", _evaluate)

    with db_factory() as db:
        worker._run_evaluation_stage(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        evaluation = evaluations_repository.get_evaluation_for_job_candidate(
            db, job_id, candidate_id
        )
        evaluated_at = evaluation.created_at
        if evaluated_at.tzinfo is None:
            evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)
        started_at = batch.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        assert evaluated_at >= started_at
        assert batch.evaluated_items == 1
        assert batch.evaluation_failed_items == 0
        assert batch.current_stage == "RANKING"

    assert calls == [candidate_id]


def test_changed_candidate_with_current_batch_evaluation_resumes_without_llm(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch, job, candidates = _seed_evaluation_batch(
            db,
            identity_created_in_batch=True,
        )
        _complete_evaluation(
            db,
            candidate_id=candidates[0].id,
            job_id=job.id,
            created_at=batch.started_at + timedelta(minutes=1),
        )
        db.commit()
        batch_id = batch.id

    monkeypatch.setattr(worker, "SessionLocal", db_factory)
    monkeypatch.setattr(
        evaluations_service,
        "evaluate_candidate_for_owner",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("current-batch terminal evaluation must resume")
        ),
    )

    with db_factory() as db:
        worker._run_evaluation_stage(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.evaluated_items == 1
        assert batch.current_stage == "RANKING"


def test_duplicate_documents_for_one_candidate_evaluate_only_once(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch, job, candidates = _seed_evaluation_batch(
            db,
            identity_created_in_batch=True,
            duplicate_first_candidate_item=True,
        )
        db.commit()
        batch_id = batch.id
        candidate_id = candidates[0].id

    calls = []
    monkeypatch.setattr(worker, "SessionLocal", db_factory)

    def _evaluate(db, *, candidate_id, job_id, owner_sub):
        calls.append(candidate_id)
        return _persist_complete_result(db, candidate_id=candidate_id, job_id=job_id)

    monkeypatch.setattr(evaluations_service, "evaluate_candidate_for_owner", _evaluate)

    with db_factory() as db:
        worker._run_evaluation_stage(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.evaluated_items == 1
        assert batch.current_stage == "RANKING"

    assert calls == [candidate_id]


def test_evaluation_executor_never_exceeds_configured_concurrency(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch, job, candidates = _seed_evaluation_batch(
            db,
            candidate_count=5,
            identity_created_in_batch=True,
        )
        db.commit()
        batch_id = batch.id

    monkeypatch.setattr(worker, "SessionLocal", db_factory)
    monkeypatch.setattr(worker, "get_import_evaluation_concurrency", lambda: 3, raising=False)

    state_lock = threading.Lock()
    commit_lock = threading.Lock()
    release = threading.Event()
    active = 0
    max_active = 0

    def _evaluate(db, *, candidate_id, job_id, owner_sub):
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
            if active == 3:
                release.set()
        assert release.wait(timeout=2)
        time.sleep(0.02)
        with commit_lock:
            result = _persist_complete_result(
                db,
                candidate_id=candidate_id,
                job_id=job_id,
            )
        with state_lock:
            active -= 1
        return result

    monkeypatch.setattr(evaluations_service, "evaluate_candidate_for_owner", _evaluate)

    with db_factory() as db:
        worker._run_evaluation_stage(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.evaluated_items == 5
        assert batch.evaluation_failed_items == 0
        assert batch.current_stage == "RANKING"

    assert max_active == 3


def test_transient_bedrock_error_retries_then_succeeds(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch, job, candidates = _seed_evaluation_batch(
            db,
            identity_created_in_batch=True,
        )
        db.commit()
        batch_id = batch.id

    monkeypatch.setattr(worker, "SessionLocal", db_factory)
    sleeps = []
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: sleeps.append(seconds))
    calls = 0

    def _evaluate(db, *, candidate_id, job_id, owner_sub):
        nonlocal calls
        calls += 1
        if calls == 1:
            evaluation = _failed_evaluation(
                db,
                candidate_id=candidate_id,
                job_id=job_id,
                internal="ThrottlingException: rate exceeded",
            )
            return evaluation, True, "ThrottlingException: rate exceeded"
        return _persist_complete_result(db, candidate_id=candidate_id, job_id=job_id)

    monkeypatch.setattr(evaluations_service, "evaluate_candidate_for_owner", _evaluate)

    with db_factory() as db:
        worker._run_evaluation_stage(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.evaluated_items == 1
        assert batch.evaluation_failed_items == 0
        assert batch.current_stage == "RANKING"

    assert calls == 2
    assert sleeps == [1]


def test_transient_bedrock_error_stops_after_three_retries(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch, job, candidates = _seed_evaluation_batch(
            db,
            identity_created_in_batch=True,
        )
        db.commit()
        batch_id = batch.id

    monkeypatch.setattr(worker, "SessionLocal", db_factory)
    sleeps = []
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: sleeps.append(seconds))
    calls = 0

    def _evaluate(db, *, candidate_id, job_id, owner_sub):
        nonlocal calls
        calls += 1
        internal = "ServiceUnavailableException: temporary provider failure"
        evaluation = _failed_evaluation(
            db,
            candidate_id=candidate_id,
            job_id=job_id,
            internal=internal,
        )
        return evaluation, True, internal

    monkeypatch.setattr(evaluations_service, "evaluate_candidate_for_owner", _evaluate)

    with db_factory() as db:
        worker._run_evaluation_stage(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.evaluated_items == 1
        assert batch.evaluation_failed_items == 1
        assert batch.current_stage == "RANKING"

    assert calls == 4
    assert sleeps == [1, 2, 4]


def test_permanent_evaluation_error_is_not_retried(
    db_factory,
    monkeypatch,
):
    with db_factory() as db:
        batch, job, candidates = _seed_evaluation_batch(
            db,
            identity_created_in_batch=True,
        )
        db.commit()
        batch_id = batch.id

    monkeypatch.setattr(worker, "SessionLocal", db_factory)
    sleeps = []
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: sleeps.append(seconds))
    calls = 0

    def _evaluate(db, *, candidate_id, job_id, owner_sub):
        nonlocal calls
        calls += 1
        internal = "ValidationException: malformed request"
        evaluation = _failed_evaluation(
            db,
            candidate_id=candidate_id,
            job_id=job_id,
            internal=internal,
        )
        return evaluation, True, internal

    monkeypatch.setattr(evaluations_service, "evaluate_candidate_for_owner", _evaluate)

    with db_factory() as db:
        worker._run_evaluation_stage(db, db.get(ImportBatch, batch_id))

    with db_factory() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.evaluated_items == 1
        assert batch.evaluation_failed_items == 1
        assert batch.current_stage == "RANKING"

    assert calls == 1
    assert sleeps == []
