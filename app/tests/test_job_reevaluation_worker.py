"""Contracts for durable asynchronous job reevaluation work."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.models import Candidate, Evaluation, Job, JobCandidate, JobReevaluationTask
from app.workers import job_reevaluations


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def _seed_job_with_candidates(db: Session, *, version: int = 2):
    job = Job(
        title="Cloud Engineer",
        description="AWS platform engineering",
        owner_sub="owner-1",
        evaluation_version=version,
    )
    current = Candidate(name="Current Candidate", owner_sub="owner-1")
    stale = Candidate(name="Stale Candidate", owner_sub="owner-1")
    outsider = Candidate(name="Other Tenant", owner_sub="owner-2")
    db.add_all([job, current, stale, outsider])
    db.flush()
    db.add_all(
        [
            JobCandidate(job_id=job.id, candidate_id=current.id),
            JobCandidate(job_id=job.id, candidate_id=stale.id),
            JobCandidate(job_id=job.id, candidate_id=outsider.id),
            Evaluation(
                candidate_id=current.id,
                job_id=job.id,
                job_evaluation_version=version,
                status="COMPLETED",
                match_score=90,
                recommendation="STRONG_MATCH",
                summary=(
                    "Current complete evaluation summary with enough detail to satisfy the "
                    "public completeness contract and prove that a current vacancy version "
                    "is reused without another model invocation."
                ),
                strengths=["AWS"],
                gaps=[],
            ),
            Evaluation(
                candidate_id=stale.id,
                job_id=job.id,
                job_evaluation_version=version - 1,
                status="COMPLETED",
                match_score=70,
                recommendation="GOOD_MATCH",
                summary=(
                    "Stale evaluation summary with enough detail to satisfy completeness "
                    "while still requiring replacement because it belongs to an older "
                    "vacancy evaluation version."
                ),
                strengths=["Python"],
                gaps=[],
            ),
        ]
    )
    task = JobReevaluationTask(
        owner_sub="owner-1",
        job_id=job.id,
        target_evaluation_version=version,
        status="PENDING",
    )
    db.add(task)
    db.commit()
    return job, current, stale, outsider, task


def test_worker_evaluates_only_stale_owned_candidates_and_materializes_once(monkeypatch):
    engine, db = _db()
    try:
        job, current, stale, outsider, task = _seed_job_with_candidates(db)
        evaluated = []
        ranked = []

        def fake_evaluate(_db, *, candidate, job, force=False):
            evaluated.append(candidate.id)
            assert force is False
            evaluation = (
                _db.query(Evaluation)
                .filter(Evaluation.job_id == job.id, Evaluation.candidate_id == candidate.id)
                .first()
            )
            evaluation.job_evaluation_version = job.evaluation_version
            evaluation.status = "COMPLETED"
            _db.commit()
            return evaluation, True, None

        monkeypatch.setattr(
            job_reevaluations.evaluations_service,
            "evaluate_candidate_for_job",
            fake_evaluate,
        )
        monkeypatch.setattr(
            job_reevaluations.ranking_service,
            "materialize_ranking_from_evaluations",
            lambda _db, **kwargs: ranked.append(kwargs) or {"ranking_version": 3},
        )

        outcome = job_reevaluations.process_job_reevaluation(db, task_id=task.id)

        assert outcome == "COMPLETED"
        assert evaluated == [stale.id]
        assert outsider.id not in evaluated
        assert ranked == [{"job_id": job.id, "owner_sub": "owner-1", "scope": "assigned"}]
        db.refresh(task)
        assert task.status == "COMPLETED"
        assert task.completed_at is not None
    finally:
        db.close()
        engine.dispose()


def test_worker_retry_does_not_duplicate_current_evaluations(monkeypatch):
    engine, db = _db()
    try:
        job, _current, stale, _outsider, task = _seed_job_with_candidates(db)
        calls = []

        def fake_evaluate(_db, *, candidate, job, force=False):
            calls.append(candidate.id)
            evaluation = (
                _db.query(Evaluation)
                .filter(Evaluation.job_id == job.id, Evaluation.candidate_id == candidate.id)
                .first()
            )
            evaluation.job_evaluation_version = job.evaluation_version
            _db.commit()
            return evaluation, True, None

        monkeypatch.setattr(job_reevaluations.evaluations_service, "evaluate_candidate_for_job", fake_evaluate)
        monkeypatch.setattr(
            job_reevaluations.ranking_service,
            "materialize_ranking_from_evaluations",
            lambda *_args, **_kwargs: {"ranking_version": 1},
        )

        assert job_reevaluations.process_job_reevaluation(db, task_id=task.id) == "COMPLETED"
        task.status = "PENDING"
        task.completed_at = None
        db.commit()
        assert job_reevaluations.process_job_reevaluation(db, task_id=task.id) == "COMPLETED"
        assert calls == [stale.id]
    finally:
        db.close()
        engine.dispose()


def test_older_task_cannot_overwrite_newer_job_version(monkeypatch):
    engine, db = _db()
    try:
        job, _current, _stale, _outsider, task = _seed_job_with_candidates(db, version=3)
        task.target_evaluation_version = 2
        db.commit()
        calls = []
        monkeypatch.setattr(
            job_reevaluations.evaluations_service,
            "evaluate_candidate_for_job",
            lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        monkeypatch.setattr(
            job_reevaluations.ranking_service,
            "materialize_ranking_from_evaluations",
            lambda *_args, **_kwargs: {"ranking_version": 1},
        )

        outcome = job_reevaluations.process_job_reevaluation(db, task_id=task.id)

        assert outcome == "SUPERSEDED"
        assert calls == []
        db.refresh(task)
        assert task.status == "COMPLETED"
        assert task.last_error_code == "SUPERSEDED_BY_NEWER_JOB_VERSION"
    finally:
        db.close()
        engine.dispose()


def test_missing_or_wrong_owner_job_fails_safely(monkeypatch):
    engine, db = _db()
    try:
        job = Job(title="Cloud Engineer", owner_sub="owner-2", evaluation_version=2)
        db.add(job)
        db.flush()
        task = JobReevaluationTask(
            owner_sub="owner-1",
            job_id=job.id,
            target_evaluation_version=2,
            status="PENDING",
        )
        db.add(task)
        db.commit()
        monkeypatch.setattr(
            job_reevaluations.ranking_service,
            "materialize_ranking_from_evaluations",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("ranking must not run")),
        )

        assert job_reevaluations.process_job_reevaluation(db, task_id=task.id) == "FAILED"
        db.refresh(task)
        assert task.status == "FAILED"
        assert task.last_error_code == "JOB_CONTEXT_MISSING"
    finally:
        db.close()
        engine.dispose()


def test_dispatch_repair_marks_timestamp_only_after_queue_success(monkeypatch):
    engine, db = _db()
    try:
        _job, _current, _stale, _outsider, task = _seed_job_with_candidates(db)
        sent = []
        monkeypatch.setattr(
            job_reevaluations.queue,
            "send_job_reevaluation",
            lambda task_id: sent.append(task_id) or "message-1",
        )

        assert job_reevaluations.dispatch_undispatched_job_reevaluations(db) == 1
        db.refresh(task)
        assert sent == [task.id]
        assert task.queue_dispatched_at is not None
        assert job_reevaluations.dispatch_undispatched_job_reevaluations(db) == 0
    finally:
        db.close()
        engine.dispose()
